"""Fixed-code scope RAW/NORM comparison at 5 MHz; no calibration edits."""
import json
from pathlib import Path
import time
import numpy as np
from calibrate_tx_waves_lan import LanScope,ROOT
from calibrate_tx23_scope import fit_sine
from zynq_bjt.desktop_transport import SshTransport,agent_archive
from zynq_bjt.frontend import Calibration

out=ROOT/'report/tx23_recalibration_20261103/scope_consistency';out.mkdir(exist_ok=False)
base=json.loads((out.parent/'mapped_grid/result.json').read_text(encoding='utf8'))
row=next(p for p in base['points'] if p['channel']==3 and p.get('frequency_hz')==5000000 and p.get('target_vpp_v')==.1)
cal=Calibration(ROOT/'data');zero=row['zero_code'];peak=round(cal.waveform_parameters('sine',5000000,.2)['peak_codes'])
r=dict(zero_code=zero,peak_codes=peak,frequency_hz=5000000,checks=[]);scope=None;agent=SshTransport()
def save():(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf8')
try:
    scope=LanScope('169.254.1.5','169.254.3.254',1);r['scope_idn']=scope.idn
    r['connected']=agent.connect('192.168.0.4','xilinx','xilinx',ROOT/'measurements/known_hosts',ROOT/'data',
        agent_archive(ROOT/'src/python/zynq_bjt'),bitfile=base['connected']['bitfile'])
    r['initialized']=agent.call('initialize');agent.call('stop');scope.setup(3,scale=.05);scope.point(5000000,0)
    agent.call('output',dict(channel=2,action='start',mode='sine_code',offset=zero,peak=peak,frequency_hz=5000000,
                            phase_degrees=0,wiring_confirmed=True))
    for tb in (5e-7,2e-7,5e-7):
        scope.write(f':TIMebase:MAIN:SCALe {tb}');scope.write(':RUN');time.sleep(2)
        instrument={k:scope.ask(f':MEASure:ITEM? {k},CHANnel3') for k in ('VAMP','VPP','VAVG','FREQ')}
        path=out/f'{len(r["checks"]):02d}.npz';error=None
        try:scope.sample(path,5000000,'sine')
        except (ValueError,AssertionError) as e:error=repr(e)
        a=np.load(path);raw=fit_sine(a['raw'],a['preamble'],5000000);screen=fit_sine(a['screen'],a['screen_preamble'],5000000)
        item=dict(timebase_s=tb,instrument=instrument,raw=raw,screen=screen,error=error,
                  difference_v=raw['vpp_v']-screen['vpp_v'],raw_lsb_v=float(a['preamble'][7]),screen_lsb_v=float(a['screen_preamble'][7]))
        r['checks'].append(item);save();print(json.dumps(item),flush=True)
except BaseException as e:r['error']=repr(e);print('ERROR',repr(e),flush=True)
finally:
    if agent.alive:
        try:r['stopped']=agent.call('stop');r['closed']=agent.close()
        except Exception as e:r['cleanup_error']=repr(e);agent.abort()
    if scope:
        try:scope.restore();r['scope_restored']=True
        except Exception as e:r['scope_restore_error']=repr(e)
        finally:scope.s.close()
    save()
