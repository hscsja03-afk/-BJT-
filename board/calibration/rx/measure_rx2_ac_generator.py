"""RX2 AC response, generator nominal High-Z sine, no production table edits.

SCPI basis: Rigol DG1000Z Programming Guide, APPL:SIN / OUTP:LOAD.
Uses an isolated copy of the released agent with a bounded statistics command.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import zipfile
from board.calibration.rx.calibrate_rx1_generator import Generator
from board.instruments.tx2_scope_zero import SerialAgent, ROOT

OUT = ROOT/'report/rx2_ac_generator_20261031'
BASE = ROOT/'build/work/rx2_ac_agent_20261031'
WRAPPER = '''from zynq_bjt.desktop_session import Session
from zynq_bjt.desktop_agent import main
original = Session.dispatch
def dispatch(self, operation, request=None, emit=lambda kind,value:None):
 if operation == 'rx_ac_statistics':
  board = self.require_board()
  assert not self.simulated
  assert all(not board.output(c).enabled for c in range(3))
  r = board.capture_statistics(50000)
  r['simulated'] = False
  r['sample_rates_hz'] = board.sample_rates_hz
  return r
 if operation not in ('status','initialize','capture','close'):
  raise ValueError('Diagnostic agent supports readout and muted initialization only')
 return original(self,operation,request,emit)
Session.dispatch = dispatch
raise SystemExit(main())
'''

def prepare():
    assert 'def require_board(' in (ROOT/'src/python/zynq_bjt/desktop_session.py').read_text(encoding='utf-8')
    OUT.mkdir(exist_ok=False)
    BASE.mkdir(exist_ok=False)
    formal=ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal'
    shutil.copytree(formal/'data',BASE/'data')
    with zipfile.ZipFile(formal/'agent.pyz') as src, zipfile.ZipFile(BASE/'agent.pyz','w',zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            if name!='__main__.py': dst.writestr(name,src.read(name))
        dst.writestr('__main__.py',WRAPPER)
    print(str(BASE))

def run():
    import time
    cal=json.loads((BASE/'data/rx2_calibration.json').read_text(encoding='utf-8'))
    r=dict(started=datetime.now(timezone(timedelta(hours=8))).isoformat(),points=[],events=[],complete=False,
           reference_basis='DG1032Z nominal High-Z sine setpoints; includes source/cable/RX2 response',
           absolute_accuracy_verified=False,phase_calibrated=False,production_calibration_changed=False,
           calibration_id=cal['calibration_id'],statistics_samples=50000)
    a=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events'],base=BASE)
    g=None;seen=set()
    def save(): (OUT/'collection.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    try:
        g=Generator(OUT/'generator.jsonl');r['generator_idn']=g.idn;g.off()
        r['initial_generator']={q:g.ask(q) for q in (':SOUR1:FUNC?',':SOUR1:VOLT?',':SOUR1:VOLT:OFFS?',':OUTP1:LOAD?',':SOUR1:TRACK?')}
        assert r['initial_generator'][':SOUR1:TRACK?'] in ('OFF','0')
        for cmd in (':SOUR1:MOD:STAT OFF',':SOUR1:SWE:STAT OFF',':SOUR1:BURS:STAT OFF',':OUTP1:LOAD INF',':SOUR1:VOLT:UNIT VPP'):
            g.write(cmd)
        assert g.ask(':SYST:ERR?').split(',')[0].strip() in ('0','+0')
        r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
        assert not any(x['enabled'] for x in r['initialized']['outputs'])
        r['baseline_statistics']=[a.call('rx_ac_statistics') for _ in range(5)]
        specs=[(f,1.) for f in (10000,20000,50000,100000,200000,300000,500000,750000,1000000,1250000,1500000,2000000,2500000,3000000,3500000,4000000,4500000,5000000,5500000,6000000)]
        specs += [(f,.05) for f in (10000,50000,100000,500000,1000000,2000000,3000000,4000000,5000000,6000000)]
        specs += [(10000,1.),(1000000,1.),(6000000,1.)]
        for index,(f,vpp) in enumerate(specs):
            g.off();g.write(':SOUR1:APPL:SIN {},{},0,0'.format(f,vpp));g.off()
            state={q:g.ask(q) for q in (':SOUR1:FUNC?',':SOUR1:FREQ?',':SOUR1:VOLT?',':SOUR1:VOLT:OFFS?',':OUTP1:LOAD?',':SYST:ERR?')}
            assert state[':SOUR1:FUNC?']=='SIN' and abs(float(state[':SOUR1:FREQ?'])-f)<.1
            assert abs(float(state[':SOUR1:VOLT?'])-vpp)<1e-6 and abs(float(state[':SOUR1:VOLT:OFFS?']))<1e-6
            assert float(state[':OUTP1:LOAD?'])>1e6 and state[':SYST:ERR?'].split(',')[0].strip() in ('0','+0')
            g.write(':OUTP1 ON');assert g.ask(':OUTP1?') in ('ON','1');time.sleep(.25)
            p=dict(index=index,frequency_hz=f,nominal_vpp=vpp,generator=state,statistics=[])
            r['points'].append(p)
            frame=a.call('capture');assert not frame['simulated'] and frame['sequence'] not in seen
            seen.add(frame['sequence']);raw=OUT/('waveform_{:02d}.json'.format(index));raw.write_text(json.dumps(frame),encoding='utf-8')
            p['waveform_file']=raw.name;p['waveform_sha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
            codes=[w&65535 for w in frame['words'][1]]
            assert all(w>>16==0 for w in frame['words'][1]) and min(codes)>256 and max(codes)<65279
            for repeat in range(6):
                stat=a.call('rx_ac_statistics');stat['discarded']=repeat==0
                assert not stat['simulated'] and stat['channels'][1]['fault_count']==0
                assert 49e6<stat['sample_rates_hz'][1]<51e6
                p['statistics'].append(stat)
            values=[s['channels'][1]['rms_code']*abs(cal['volts_per_code'])*2*math.sqrt(2) for s in p['statistics'][1:]]
            p.update(measured_vpp_sine_rms=statistics.fmean(values),repeat_span_vpp=max(values)-min(values))
            p['gain']=p['measured_vpp_sine_rms']/vpp;p['gain_db']=20*math.log10(p['gain'])
            assert .05<p['gain']<2, 'Unexpected response/connection; stopped'
            g.off();save()
            print(json.dumps({k:p[k] for k in ('frequency_hz','nominal_vpp','measured_vpp_sine_rms','gain_db')}),flush=True)
        r['final_status']=a.call('status');assert not any(x['enabled'] for x in r['final_status']['outputs'])
        assert r['final_status']['gpio']==r['initialized']['gpio']
        r['complete']=True
    except BaseException as exc:
        r['error']=repr(exc);raise
    finally:
        if g:
            try:g.off();r['generator_off_confirmed']=True
            except Exception as exc:r['generator_cleanup_error']=repr(exc)
            finally:g.s.close()
        try:r['board_close']=a.close()
        except Exception as exc:r['board_cleanup_error']=repr(exc)
        save();print(json.dumps({k:r.get(k) for k in ('complete','error','generator_off_confirmed','board_close')}),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prepare',action='store_true');args=ap.parse_args()
    prepare() if args.prepare else run()
