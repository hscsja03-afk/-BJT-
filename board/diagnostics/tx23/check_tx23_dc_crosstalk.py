"""Compare scope automatic VAVG with direct waveform means and channel display states."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import json,os,time
from pathlib import Path
import numpy as np
from board.calibration.tx.calibrate_tx23_scope import Scope
from board.instruments.tx2_scope_zero import ROOT, SerialAgent

out=ROOT/'report/tx23_calibration_20261030/dc_crosstalk';out.mkdir(exist_ok=False)
r={'events':[],'points':[]};agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events']);s=None
def save():(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
def raw_mean(label):
    s.write(':RUN');time.sleep(.5);s.write(':STOP')
    s.write(':WAVeform:SOURce CHAN3');s.write(':WAVeform:FORMat BYTE')
    result={};arrays={}
    for mode,count in [('RAW',s.depth),('NORM',1200)]:
        s.write(':WAVeform:MODE '+mode);s.write(':WAVeform:STARt 1');s.write(f':WAVeform:STOP {count}')
        pre=[float(x) for x in s.ask(':WAVeform:PREamble?').split(',')]
        block=s.ask_raw(b':WAVeform:DATA?');nd=int(block[1:2]);n=int(block[2:2+nd]);raw=np.frombuffer(block[2+nd:2+nd+n],dtype=np.uint8)
        arrays[mode+'_raw']=raw;arrays[mode+'_pre']=pre
        np.savez_compressed(out/(label+'.npz'),**arrays)
        assert len(raw)==count
        y=(raw.astype(float)-pre[8]-pre[9])*pre[7]
        result[mode]=dict(mean_v=float(np.mean(y)),std_v=float(np.std(y)),min_v=float(y.min()),max_v=float(y.max()),preamble=pre)
    return result
try:
    s=Scope();r['connected']=agent.connect();r['initialized']=agent.call('initialize',timeout=120)
    r['tx2']=agent.call('output',dict(channel=1,action='start',wiring_confirmed=True,mode='dc_voltage',offset=.5))
    s.setup(3)
    for f in (100000,6000000):
        state=agent.call('output',dict(channel=2,action='start',wiring_confirmed=True,mode='sine_voltage',frequency_hz=f,offset=0,vpp=.05))
        for on in (False,True,False):
            s.write(':CHANnel4:DISPlay '+('ON' if on else 'OFF'))
            s.write(':CHANnel4:SCALe .01');s.write(':CHANnel4:OFFSet 0')
            s.depth=6000 if on else 12000
            s.write(':RUN');s.write(f':ACQuire:MDEPth {s.depth}');s.write(':TRIGger:EDGe:SOURce CHAN4' if on else ':TRIGger:EDGe:SOURce CHAN3')
            m=s.dc(.5,repeats=7);wave=raw_mean('point'+str(len(r['points'])))
            p=dict(tx3_hz=f,scope_ch4_display=on,outputs_state=state,automatic=m,waveforms=wave)
            r['points'].append(p);save()
            print(json.dumps(dict(f=f,display4=on,auto=m['mean_v'],raw=wave['RAW']['mean_v'],screen=wave['NORM']['mean_v'])),flush=True)
except BaseException as e:r['error']=repr(e);raise
finally:
    try:r['close']=agent.close()
    except Exception as e:r['cleanup_error']=repr(e)
    if s:
        try:s.restore()
        except Exception as e:r['scope_restore_error']=repr(e)
        try:s.s.close()
        except Exception as e:r['scope_close_error']=repr(e)
    save();print(json.dumps({k:r.get(k) for k in ('close','error')}),flush=True)
