"""Real SSH desktop path: read-only board status and no-init command rejection."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/python'))
sys.path.insert(0, str(ROOT/'build/tool_deps/ssh_runtime'))
from zynq_bjt.desktop_transport import SshTransport, agent_archive

events = []
transport = SshTransport(lambda kind, value: events.append({'kind': kind, 'value': value}))
evidence = dict(timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'), operations=[], analog_outputs_enabled=False)
try:
    evidence['before'] = transport.connect('192.168.0.4', 'xilinx', os.environ['PYNQ_SSH_PASSWORD'],
        ROOT/'build/work/pynq_jtag_boot/known_hosts', ROOT/'data', agent_archive(ROOT/'src/python/zynq_bjt'))
    assert not evidence['before']['initialized']
    for operation, args in [('scan', {'measurement': 'input'}), ('unsupported', {})]:
        try: transport.call(operation, args)
        except RuntimeError as error:
            evidence['operations'].append(dict(operation=operation, rejected=True, error=str(error)))
        else: raise AssertionError('Expected explicit rejection: '+operation)
    evidence['after'] = transport.call('status')
    for key in ('registers', 'control', 'dac_mode', 'identity'):
        assert evidence['before'][key] == evidence['after'][key]
    evidence['close'] = transport.close()
    evidence['passed'] = True
finally:
    transport.abort()
    evidence['events'] = events
    (ROOT/'report/desktop_connection_20261030.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print('Read-only desktop connection verified; hardware was not initialized.')
