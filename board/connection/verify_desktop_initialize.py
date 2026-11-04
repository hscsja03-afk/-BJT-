"""Exercise the shipped SSH/session initialization while all TX outputs stay muted."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/python'))
sys.path.insert(0, str(ROOT/'build/tool_deps/ssh_runtime'))
from zynq_bjt.desktop_transport import SshTransport, agent_archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--agent', type=Path)
    args = parser.parse_args()
    evidence = {'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S'), 'passed':False,
                'analog_output_enable_commands':0, 'events':[]}
    transport = SshTransport(lambda k,v: evidence['events'].append({'kind':k,'value':v}))
    archive = args.agent.read_bytes() if args.agent else agent_archive(ROOT/'src/python/zynq_bjt')
    evidence['agent_sha256'] = hashlib.sha256(archive).hexdigest()
    evidence['agent_source'] = str(args.agent.resolve()) if args.agent else 'workspace source archive'
    try:
        evidence['connected'] = transport.connect('192.168.0.4', 'xilinx', os.environ['PYNQ_SSH_PASSWORD'],
            ROOT/'build/work/pynq_jtag_boot/known_hosts', ROOT/'data', archive)
        evidence['initialized'] = transport.call('initialize', timeout=120)
        assert evidence['initialized']['initialized']
        assert evidence['initialized']['identity']['digital_self_test'] == 'passed'
        assert all(not s['enabled'] for s in evidence['initialized']['outputs'])
        frame = transport.call('capture', timeout=20)
        evidence['raw_capture'] = {'sequence':frame['sequence'], 'sample_rates_hz':frame['sample_rates_hz'],
            'simulated':frame['simulated'], 'channels':[
                {'count':len(w), 'min_code':min(v&65535 for v in w), 'max_code':max(v&65535 for v in w),
                 'overrange':sum(v>>16 for v in w)} for w in frame['words']]}
        assert not frame['simulated']
        assert all(len(w)==1024 for w in frame['words'])
        evidence['status_after_capture'] = transport.call('status')
        assert all(not s['enabled'] for s in evidence['status_after_capture']['outputs'])
        evidence['close'] = transport.close()
        assert evidence['close']['closed'] and evidence['close']['cleanup_confirmed']
        evidence['passed'] = True
    except BaseException as error:
        evidence['error'] = repr(error)
        raise
    finally:
        if transport.alive:
            try: evidence['close_after_failure'] = transport.close()
            except Exception as error: evidence['cleanup_error'] = repr(error)
        transport.abort()
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k in ('passed','raw_capture','close')},indent=2))


if __name__ == '__main__': main()
