"""Offline end-to-end exercise of four BJT profiles and four measurements."""
import argparse
from datetime import datetime
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src/python'))
from zynq_bjt.desktop_session import Session, MEASUREMENTS
from zynq_bjt.profiles import defaults_for

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[3]
    result=dict(at=datetime.now().astimezone().isoformat(),checks=[],passed=False,simulated=True)
    expected={'npn_small':{'input':64,'output':4,'beta':4,'ac':2},
              'npn_big':{'input':65,'output':37,'beta':37,'ac':35},
              'pnp_small':{'input':88,'output':28,'beta':28,'ac':26},
              'pnp_big':{'input':89,'output':61,'beta':61,'ac':59}}
    session=Session(root/'data',a.out/'runs',simulated=True)
    try:
        session.initialize()
        for profile in expected:
            for name,(cls,runner,csvname) in MEASUREMENTS.items():
                cfg=defaults_for(name,cls,profile);cfg['settle_s']=0
                if name=='input':cfg.update(tx1_stop_v=.1,tx1_step_v=.02,uce_values_v=(1,2),curve_settle_s=0,frame_gap_s=0,frames_per_point=2)
                if name=='output':cfg.update(base_control_v=(.05,.15),frames_per_point=2)
                if name=='beta':cfg.update(tx1_stop_v=.08,frames_per_point=2,moving_average_window=1)
                if name=='ac':cfg.update(repeat_count=2,max_bisection_iterations=2)
                session.board.gpio(127,0x55)
                run=session.scan(dict(measurement=name,profile=profile,config=cfg))
                state=run['state']
                check=dict(profile=profile,measurement=name,status=state['status'],error=state.get('error'),directory=run['directory'])
                result['checks'].append(check)
                assert state['status']=='complete',check
                route=state['measurement_gpio'] if name=='input' else state['source_parameters']
                actual=route['value'] if name=='input' else route['gpio_value']
                assert actual==expected[profile][name],(profile,name,actual)
                assert not any(session.board.enabled)
                assert session.board.gpio_value==0x55
                with (Path(run['directory'])/csvname).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
                assert rows and all(r['simulated']=='1' and r['profile']==profile for r in rows)
                check.update(rows=len(rows),gpio=actual,cleanup_confirmed=True)
                if name=='beta':
                    assert 80<state['beta']['beta_mean']<130,state['beta']
                    check['beta_mean']=state['beta']['beta_mean']
                print(json.dumps(check),flush=True)
        result['passed']=True
    except BaseException as error:
        result['error']=repr(error)
        raise
    finally:
        result['close']=session.close()
        (a.out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
