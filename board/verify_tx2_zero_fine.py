"""Check enabled TX2 zero at 10 mV/div, including scope internal-ground reference."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
from tx2_scope_zero import SerialAgent, vxi11, read_scope

ROOT=Path(__file__).resolve().parents[1]
PREFIX=ROOT/'report'/('tx2_zero_fine_'+datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S'))
evidence={'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
          'events':[], 'procedure_completed':False, 'analog_calibration_qualified':False}
agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],evidence['events'])
scope=vxi11.Instrument('169.254.1.5');scope.timeout=5
prior={}
def measure(label):
    time.sleep(.5)
    values=[]
    for _ in range(7):
        time.sleep(.15)
        value=float(scope.ask(':MEASure:ITEM? VAVG,CHANnel3'))
        if not -.04<value<.04: raise RuntimeError('Fine-range measurement clipped or invalid')
        values.append(value)
    snapshot=read_scope('169.254.1.5',3,PREFIX.with_name(PREFIX.name+'_'+label),
                        'User confirmed CH3 on repaired ADDA TX2; requested 0 V',scope=scope)
    result={'readings_v':values,'mean_v':sum(values)/len(values),'scope':snapshot}
    print(label,result['mean_v'],flush=True)
    return result
try:
    if 'DS1104Z,DS1ZA173719283,' not in scope.ask('*IDN?'): raise RuntimeError('Unexpected instrument')
    for key in (':CHANnel3:SCALe',':CHANnel3:OFFSet',':CHANnel3:COUPling'):
        prior[key]=scope.ask(key+'?').strip()
    evidence['scope_before']=prior
    scope.write(':CHANnel3:SCALe 0.01');scope.write(':CHANnel3:OFFSet 0');scope.write(':CHANnel3:COUPling DC')
    evidence['connected']=agent.connect()
    evidence['initialized']=agent.call('initialize',timeout=120)
    evidence['zero_setpoint']=agent.call('output',dict(channel=1,action='start',mode='dc_voltage',offset=0,wiring_confirmed=True))
    out=evidence['zero_setpoint']['outputs']
    profile=json.loads((ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal/data/dac_calibration.json').read_text())
    assert out[1]['enabled'] and out[1]['code']==profile['channels'][1]['dc_table']['codes'][0]
    assert not out[0]['enabled'] and not out[2]['enabled']
    evidence['dc_before']=measure('dc_before')
    scope.write(':CHANnel3:COUPling GND')
    evidence['scope_internal_ground']=measure('internal_ground')
    scope.write(':CHANnel3:COUPling DC')
    evidence['dc_after']=measure('dc_after')
    evidence['procedure_completed']=True
except BaseException as error:
    evidence['error']=repr(error)
    raise
finally:
    try:evidence['close']=agent.close()
    except Exception as error:evidence['board_cleanup_error']=repr(error)
    try:
        for key,value in prior.items():scope.write(key+' '+value)
        evidence['scope_restored']={key:scope.ask(key+'?').strip() for key in prior}
    except Exception as error:evidence['scope_restore_error']=repr(error)
    try:scope.close()
    except Exception as error:evidence['scope_close_error']=repr(error)
    PREFIX.with_suffix('.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:evidence.get(k) for k in ('procedure_completed','close','error','board_cleanup_error','scope_restore_error')},indent=2),flush=True)
