"""Prepare a reviewable startup-only update from audited installed state."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--deployment',type=Path,required=True)
p.add_argument('--before',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
args=p.parse_args()
deployment=json.loads(args.deployment.read_text(encoding='utf8'))
assert deployment['verified']
audit=json.loads(args.before.read_text(encoding='utf8'))
assert audit['complete']
line=next(line for line in audit['output'].splitlines() if line.startswith('DESKTOP_STARTUP_AUDIT '))
before=json.loads(line.split(' ',1)[1]);source=before['startup_source']
previous=before['ready_record'];identity=previous['identity']
replacements={previous['agent']:deployment['remote']+'/agent.pyz',
              previous['agent_sha256']:deployment['files']['agent.pyz'],
              identity['bit_sha256']:before['overlay']['bjt.bit'],
              identity['hwh_sha256']:before['overlay']['bjt.hwh']}
for old,new in replacements.items():
    assert source.count(old)==1,(old,source.count(old))
    source=source.replace(old,new)
assert 'adc_divider=20,dac_divider=8' in source
calibration_files={k:sha for k,sha in deployment['files'].items() if k.startswith('data/')}
checks=('expected_data='+repr(calibration_files)+'\n'
        'for name,expected in expected_data.items():\n'
        ' assert hashlib.sha256((agent.parent/name).read_bytes()).hexdigest()==expected,name\n')
source=source.replace('sys.path.insert(0,str(agent))',checks+'sys.path.insert(0,str(agent))')
compile(source,'startup','exec')
guard=("from pathlib import Path\nimport hashlib\n"
       "assert hashlib.sha256(Path('/usr/local/lib/zynq_bjt_autostart.py').read_bytes()).hexdigest()=="+
       repr(before['startup_sha256'])+", 'Startup changed since audit'\n")
payload=guard+'DEPLOYMENT='+repr(deployment)+'\nSTARTUP_SOURCE='+repr(source)+'\n'+(ROOT/'board/update_persistent_agent.py').read_text(encoding='utf8')
args.out.write_text(payload,encoding='utf8')
args.out.with_suffix('.startup.py').write_text(source,encoding='utf8')
print('Prepared startup update:',args.out)
