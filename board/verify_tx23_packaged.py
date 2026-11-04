"""Independently exercise packaged voltage modes, including frequency-only edits."""
import argparse
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import time
import numpy as np
from calibrate_tx23_scope import Scope
from tx2_scope_zero import ROOT,SerialAgent
from read_scope import read_scope


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--dc-evidence',type=Path,help='Reuse completed DC measurements from the identical packaged agent/data')
    ap.add_argument('--sine-evidence',type=Path,help='Reuse valid sine fits while rechecking simultaneous DC with the DC acquisition method')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    r=dict(started=datetime.now(timezone(timedelta(hours=8))).isoformat(),events=[],dc=[],sine=[],passed=False)
    agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events']);s=None
    def save():(args.out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    def output(ch,**kw):return agent.call('output',dict(channel=ch,action='start',wiring_confirmed=True,**kw))
    try:
        s=Scope();r.update(scope_idn=s.idn,scope_before=s.prior,connected=agent.connect())
        r['initialized']=agent.call('initialize',timeout=120)
        if args.dc_evidence:
            prior=json.loads(args.dc_evidence.read_text())
            assert prior['connected']['remote']==r['connected']['remote'] and prior['close']['cleanup_confirmed']
            assert len(prior['dc'])==10
            r.update(dc=prior['dc'],dc_verification_source=str(args.dc_evidence),tx2_zero_screenshot=prior['tx2_zero_screenshot'])
        else:
            s.setup(3)
            for v in (0,.0125,.05,.1,.325,.8,1.475,1.8,.5,0):
                state=output(1,mode='dc_voltage',offset=v)
                m=s.dc(v,repeats=7)
                p=dict(request_v=v,state=state,measurement=m,error_v=m['mean_v']-v)
                r['dc'].append(p);save();print(f'TX2 {v:.4f}V -> {m["mean_v"]:.6f}V',flush=True)
            r['tx2_zero_screenshot']=read_scope('169.254.1.5',3,args.out/'tx2_zero','TX2 to CH3; packaged voltage 0 V enabled',scope=s.s)
        # Hold TX2 at 0.5 V while TX3 is swept to verify simultaneous operation.
        output(1,mode='dc_voltage',offset=.5)
        s.setup(4,sine=True)
        s.write(':CHANnel3:DISPlay ON');s.write(':CHANnel3:SCALe 0.01');s.write(':CHANnel3:OFFSet -0.5')
        s.depth=6000
        s.write(':ACQuire:MDEPth 6000')
        sine_prior=None
        if args.sine_evidence:
            sine_prior=json.loads(args.sine_evidence.read_text())
            assert sine_prior['connected']['remote']==r['connected']['remote'] and sine_prior['close']['cleanup_confirmed']
            assert len(sine_prior['sine'])==7
            r['sine_verification_source']=str(args.sine_evidence)
        for i,f in enumerate((10000,100000,1000000,6000000,1000000,55000,2550000)):
            state=output(2,mode='sine_voltage',frequency_hz=f,vpp=.05,offset=0)
            assert state['outputs'][1]['enabled'] and state['outputs'][2]['enabled'] and not state['outputs'][0]['enabled']
            s.point(f)
            rows=[]
            if sine_prior:
                old=sine_prior['sine'][i];assert old['requested_hz']==f
                rows=old['individual']
                snapshot_dc=old['tx2_simultaneous_v']
            else:
                for j in range(3):
                    for attempt in range(3):
                        path=args.out/f'sine{i}_{j}_try{attempt}.npz'
                        try:rows.append(s.capture(path,f));break
                        except AssertionError as e:
                            r.setdefault('rejected_acquisitions',[]).append(dict(path=str(path),reason=str(e)));save()
                            if attempt==2:raise
                            s.write(':CHANnel4:SCALe .02');s.write(':CHANnel4:SCALe .01');s.point(f)
                snapshot_dc=float(s.ask(':MEASure:ITEM? VAVG,CHANnel3'))
            # Validate DC with the same running, 100 us/div HRES method used
            # for calibration, rather than a short stopped sine acquisition.
            s.write(':ACQuire:TYPE HRES');s.write(':TIMebase:MAIN:SCALe .0001')
            s.channel=3
            dc_simultaneous=s.dc(.5,repeats=7)
            s.channel=4
            p=dict(requested_hz=f,state=state,individual=rows,
                   vpp_v=float(np.mean([x['vpp_v'] for x in rows])),dc_v=float(np.mean([x['dc_v'] for x in rows])),
                   tx2_simultaneous_v=dc_simultaneous['mean_v'],tx2_simultaneous_measurement=dc_simultaneous,
                   tx2_short_sine_snapshot_v=snapshot_dc)
            p['error_v']=p['vpp_v']-.05;r['sine'].append(p);save()
            print(f'TX3 {f}Hz -> {p["vpp_v"]*1000:.4f}mVpp, DC={p["dc_v"]*1000:.3f}mV, TX2={p["tx2_simultaneous_v"]:.6f}V',flush=True)
        s.point(f);s.write(':ACQuire:TYPE NORM');s.write(':RUN');time.sleep(.5)
        r['screenshot']=read_scope('169.254.1.5',4,args.out/'tx23_together','TX2 0.5 V to CH3; TX3 50 mVpp sine to CH4; both enabled',scope=s.s)
        r['tx2_max_error_v']=max(abs(p['error_v']) for p in r['dc'])
        r['tx3_max_vpp_error_v']=max(abs(p['error_v']) for p in r['sine'])
        r['tx3_max_dc_error_v']=max(abs(p['dc_v']) for p in r['sine'])
        r['tx2_simultaneous_max_error_v']=max(abs(p['tx2_simultaneous_v']-.5) for p in r['sine'])
        r['passed']=(r['tx2_max_error_v']<.0015 and r['tx3_max_vpp_error_v']<.00075 and
                     r['tx3_max_dc_error_v']<.002 and r['tx2_simultaneous_max_error_v']<.0015)
    except BaseException as e:r['error']=repr(e);raise
    finally:
        try:r['close']=agent.close()
        except Exception as e:r['cleanup_error']=repr(e)
        if s:
            try:s.restore();r['scope_restored']=True
            except Exception as e:r['scope_restore_error']=repr(e)
            try:s.s.close()
            except Exception as e:r['scope_close_error']=repr(e)
        r['ended']=datetime.now(timezone(timedelta(hours=8))).isoformat();save()
        print(json.dumps({k:v for k,v in r.items() if k in ('passed','error','close','tx2_max_error_v','tx3_max_vpp_error_v','tx3_max_dc_error_v')},indent=2),flush=True)


if __name__=='__main__':main()
