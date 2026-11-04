"""Repeat the user's completed NPN small input sweep with balanced timing."""
import json
import argparse
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.desktop_transport import SshTransport, agent_archive

out = ROOT/'report/desktop_responsiveness_20261031'
out.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--baseline', action='store_true')
args = parser.parse_args()
r = dict(events=[], passed=False)
start = time.monotonic()
def emit(kind, value):
    r['events'].append(dict(kind=kind, elapsed_s=time.monotonic()-start, value=value))
    if kind == 'point' and value.get('index', 0) % 10 == 0:
        print('POINT {}: UBE={:.5f} V, UCE={:.5f} V'.format(value['index']+1, value['ube_v'], value['uce_v']), flush=True)
t = SshTransport(emit)
try:
    r['connected'] = t.connect('192.168.0.4', 'xilinx', os.environ['PYNQ_SSH_PASSWORD'],
        ROOT/'measurements/known_hosts', ROOT/'data', agent_archive(ROOT/'src/python/zynq_bjt'))
    r['initialized'] = t.call('initialize')
    request = json.loads((ROOT/'measurements/npn_input_balanced.json').read_text(encoding='utf-8'))
    if args.baseline:
        request['config'].update(settle_s=.05, curve_settle_s=.5, frames_per_point=3, frame_gap_s=.05, adaptive_settle_v=0)
    request.update(profile='npn_small', fixture_confirmed=True, allow_reference=True)
    start = time.monotonic()
    result = t.call('scan', request, timeout=180)
    r['result'] = result
    r['local_directory'] = str(t.fetch(result, ROOT/'measurements/results'))
    r['status'] = t.call('status')
    assert not any(s['enabled'] for s in r['status']['outputs'])
    state = result['state']
    old = json.loads((ROOT/'measurements/results/20261031_013531_c48bb22a/run.json').read_text())
    times = [e['elapsed_s'] for e in r['events'] if e['kind']=='point']
    duration = state['finished_at'] - state['started_at']
    old_duration = old['finished_at'] - old['started_at']
    r['timing'] = dict(previous_duration_s=old_duration, duration_s=duration,
        first_point_s=times[0] if times else None,
        median_point_gap_s=statistics.median(b-a for a,b in zip(times,times[1:])) if len(times)>1 else None,
        time_reduction_percent=(1-duration/old_duration)*100)
    assert state['status']=='complete' and state['points']==41, (state['status'], state.get('error'))
    r['passed'] = True
finally:
    try: r['closed'] = t.close()
    except Exception as exc: r['cleanup_error'] = repr(exc)
    (out/('hardware_baseline.json' if args.baseline else 'hardware_pacing.json')).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(passed=r['passed'], timing=r.get('timing'), closed=r.get('closed')), ensure_ascii=False))
