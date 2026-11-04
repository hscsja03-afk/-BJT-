"""Current RX2 DC calibration against DG1032Z nominal High-Z setpoints.

User-confirmed CH1 -> RX2, transistor fixture disconnected. Removed input
shunts make the historical 50-ohm display setting inappropriate; R153 is AFTER
the buffer. No absolute-voltage or AC calibration claim. All raw frames are
retained and the generator/three board outputs are closed on exit.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
from board.instruments.tx2_scope_zero import SerialAgent, ROOT
from board.instruments.read_scope import vxi11


from board.calibration.rx.calibrate_rx1_generator import Generator


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--probe', action='store_true')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    result = dict(started=datetime.now().astimezone().isoformat(),
                  connection='User confirmed DG1032Z CH1 directly to RX2; BJT fixture disconnected',
                  reference_basis='DG1032Z nominal DC offset, High-Z display, no external voltage measurement',
                  absolute_voltage_accuracy_verified=False, ac_response_calibrated=False,
                  hardware_revision=json.loads((ROOT/'data/hardware_revision.json').read_text(encoding='utf-8')),
                  channel_index=1, channel='RX2 / ADC A',
                  events=[], points=[], complete=False)
    agent = SerialAgent('COM7', os.environ['PYNQ_SSH_PASSWORD'], result['events'])
    gen = None
    sequence = set()

    def save():
        (args.out/'collection.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    def point(label, volts, role):
        row = dict(label=label, requested_v=volts, reference_v_nominal=volts,
                   role=role, captures=[], accepted=False)
        result['points'].append(row)
        try:
            row['generator'] = gen.dc(volts)
            time.sleep(.3)
            for repeat in range(4):
                frame = agent.call('capture', timeout=20)
                path = args.out/(label+'_'+str(repeat)+'.json')
                path.write_text(json.dumps(frame), encoding='utf-8')
                assert not frame['simulated'] and frame['sequence'] not in sequence
                sequence.add(frame['sequence'])
                assert all(49e6 < r < 51e6 for r in frame['sample_rates_hz']), frame['sample_rates_hz']
                words = frame['words'][1]
                codes = [w & 65535 for w in words]
                stats = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             sequence=frame['sequence'], discarded=repeat==0,
                             samples=len(codes), mean_code=statistics.fmean(codes),
                             std_code=statistics.pstdev(codes), min_code=min(codes),
                             max_code=max(codes), overrange=sum(bool(w>>16) for w in words),
                             sample_rate_hz=frame['sample_rates_hz'][1])
                row['captures'].append(stats)
                if stats['overrange'] or min(codes) < 256 or max(codes) > 65279:
                    row['rejection'] = 'overrange_or_near_rail'
                    break
            valid = [c for c in row['captures'] if not c['discarded']]
            if 'rejection' not in row and len(valid)==3:
                row['mean_code'] = statistics.fmean(c['mean_code'] for c in valid)
                row['frame_drift_code'] = max(c['mean_code'] for c in valid)-min(c['mean_code'] for c in valid)
                row['accepted'] = max(c['std_code'] for c in valid) < 60 and row['frame_drift_code'] < 30
                if not row['accepted']: row['rejection'] = 'unstable_dc'
        finally:
            gen.off()
            save()
        print(json.dumps({k: row.get(k) for k in ('label','reference_v_nominal','mean_code','accepted','rejection')}), flush=True)
        return row

    try:
        gen = Generator(args.out/'generator.jsonl')
        result['generator_idn'] = gen.idn
        result['generator_initial'] = {q: gen.ask(q) for q in
                                      (':OUTP1?', ':OUTP1:LOAD?', ':SOUR1:FUNC?', ':SOUR1:VOLT:OFFS?')}
        gen.off()
        # Retain and drain prior errors before the bounded sequence.
        result['prior_errors'] = []
        for _ in range(12):
            error = gen.ask(':SYST:ERR?'); result['prior_errors'].append(error)
            if error.split(',')[0].strip() in ('0', '+0'): break
        result['connected'] = agent.connect()
        result['initialized'] = agent.call('initialize', timeout=120)
        assert all(not out['enabled'] for out in result['initialized']['outputs'])
        zero = point('zero_initial', 0, 'fit')
        assert zero['accepted'], 'No stable zero reference'
        limits = {1: 0, -1: 0}
        for magnitude in ([.05,.1] if args.probe else [.05,.1,.25,.5,.75,1,1.25,1.5,1.75,2]):
            for sign in (1,-1):
                if limits[sign] is None: continue
                row = point(('p' if sign>0 else 'm')+str(magnitude).replace('.','p'), sign*magnitude, 'fit')
                if not row['accepted']:
                    limits[sign] = None
                    continue
                if magnitude==.1:
                    assert abs(row['mean_code']-zero['mean_code']) > 100, 'Missing RX2 input response'
                limits[sign] = magnitude
        if not args.probe:
            for sign in (1,-1):
                edge = max([abs(p['reference_v_nominal']) for p in result['points']
                            if p['accepted'] and p['reference_v_nominal']*sign > 0] or [0])
                held = [.025,.075,.175,.375,.625,.875,1.125,1.375,1.625,1.875]
                for magnitude in reversed([v for v in held if v < edge]):
                    point(('vp' if sign>0 else 'vm')+str(magnitude).replace('.','p'), sign*magnitude, 'validation')
            point('zero_final', 0, 'validation')
        result['complete'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        if gen is not None:
            try: gen.off(); result['generator_output_off_confirmed'] = True
            except Exception as error: result['generator_cleanup_error'] = repr(error)
            gen.s.close()
        try: result['board_close'] = agent.close()
        except Exception as error: result['board_cleanup_error'] = repr(error)
        save()
        print(json.dumps({k: result.get(k) for k in ('complete','error','generator_output_off_confirmed','board_close')}), flush=True)


if __name__ == '__main__': main()
