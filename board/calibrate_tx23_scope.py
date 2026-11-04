"""Scope-relative TX2 DC / TX3 sine calibration, UART control and one LAN link.

Reference: Rigol DS1000Z Programming Guide; original embedded sine-fit method.
Never writes calibration data automatically. Every run leaves all outputs off.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np
from tx2_scope_zero import SerialAgent, ROOT
from read_scope import vxi11, read_scope


def fit_sine(raw, pre, expected):
    y = (raw.astype(float)-pre[8]-pre[9])*pre[7]
    t = (np.arange(len(y))-(len(y)-1)/2)*pre[4]
    f = float(expected)
    def design(hz):
        w = 2*np.pi*hz*t
        return np.column_stack([np.ones(len(t)), t/(len(t)*pre[4])]+
                               [fn(k*w) for k in (1,2,3) for fn in (np.sin,np.cos)])
    for _ in range(6):
        x = design(f); b = np.linalg.lstsq(x,y,rcond=None)[0]
        derivative = 2*np.pi*t*(b[2]*np.cos(2*np.pi*f*t)-b[3]*np.sin(2*np.pi*f*t))
        delta = float(np.linalg.lstsq(np.column_stack((x,derivative)),y-x@b,rcond=None)[0][-1])
        f += delta
        if abs(delta)<expected*1e-9: break
    x = design(f); b = np.linalg.lstsq(x,y,rcond=None)[0]
    amp = float(np.hypot(b[2],b[3]))
    assert abs(f/expected-1)<.005, ('frequency mismatch', f, expected)
    assert raw.min()>2 and raw.max()<253, ('clipping',int(raw.min()),int(raw.max()))
    assert len(y)*pre[4]*f>=10 and 1/pre[4]/f>=20, ('insufficient sampling',pre[4],f)
    return dict(frequency_hz=f, vpp_v=2*amp, dc_v=float(b[0]),
                residual_rms_v=float(np.std(y-x@b)), raw_vpp_v=float(np.ptp(y)),
                thd_2_3=float(np.hypot(np.hypot(b[4],b[5]),np.hypot(b[6],b[7]))/amp),
                raw_min=int(raw.min()), raw_max=int(raw.max()), samples=len(y), sample_rate_hz=1/pre[4])


class Scope:
    def __init__(self):
        self.s = vxi11.Instrument('169.254.1.5'); self.s.timeout = 8
        self.last = 0
        self.idn = self.ask('*IDN?')
        if 'DS1104Z,DS1ZA173719283,' not in self.idn: raise RuntimeError('Wrong instrument')
        keys = [f':CHANnel{i}:DISPlay' for i in range(1,5)]
        keys += [f':CHANnel{i}:{k}' for i in (3,4) for k in
                 ('PROBe','COUPling','INVert','BWLimit','SCALe','OFFSet')]
        keys += [':TIMebase:MODE', ':TIMebase:MAIN:SCALe', ':TIMebase:MAIN:OFFSet',
                 ':ACQuire:MDEPth', ':ACQuire:TYPE', ':TRIGger:MODE', ':TRIGger:EDGe:SOURce',
                 ':TRIGger:EDGe:SLOPe', ':TRIGger:EDGe:LEVel', ':TRIGger:SWEep',
                 ':WAVeform:SOURce', ':WAVeform:MODE', ':WAVeform:FORMat']
        self.prior = {k:self.ask(k+'?') for k in keys}
        self.channel = None
        self.depth = 12000

    def call(self, method, value):
        time.sleep(max(0,.07-(time.monotonic()-self.last)))
        try: return getattr(self.s,method)(value)
        finally: self.last = time.monotonic()
    def ask(self,q): return self.call('ask',q).strip()
    def write(self,q): return self.call('write',q)
    def ask_raw(self,q): return self.call('ask_raw',q)

    def setup(self,channel,sine=False,scale=.01):
        self.channel = channel
        cmds = [':STOP']+[f':CHANnel{i}:DISPlay '+('ON' if i==channel else 'OFF') for i in range(1,5)]
        cmds += [f':CHANnel{channel}:PROBe 1', f':CHANnel{channel}:COUPling DC',
                 f':CHANnel{channel}:INVert OFF', f':CHANnel{channel}:BWLimit OFF',
                 f':CHANnel{channel}:SCALe {scale}', f':CHANnel{channel}:OFFSet 0',
                 ':TIMebase:MODE MAIN', ':TIMebase:MAIN:OFFSet 0', ':TIMebase:MAIN:SCALe 0.0001',
                 ':ACQuire:TYPE '+('NORM' if sine else 'HRES'), ':TRIGger:MODE EDGE',
                 f':TRIGger:EDGe:SOURce CHAN{channel}', ':TRIGger:EDGe:SLOPe POS',
                 ':TRIGger:EDGe:LEVel 0', ':TRIGger:SWEep AUTO',
                 f':WAVeform:SOURce CHAN{channel}', ':WAVeform:FORMat BYTE', ':RUN']
        for c in cmds: self.write(c)
        self.depth = 12000
        if sine: self.write(f':ACQuire:MDEPth {self.depth}')
        self.scale = float(self.ask(f':CHANnel{channel}:SCALe?'))
        assert self.scale == scale

    def dc(self, center, repeats=5):
        ch = self.channel
        self.write(f':CHANnel{ch}:OFFSet {-center:.9f}')
        self.write(':RUN'); time.sleep(.35)
        vals = [float(self.ask(f':MEASure:ITEM? VAVG,CHANnel{ch}')) for _ in range(repeats)]
        lo = float(self.ask(f':MEASure:ITEM? VMIN,CHANnel{ch}'))
        hi = float(self.ask(f':MEASure:ITEM? VMAX,CHANnel{ch}'))
        offset = float(self.ask(f':CHANnel{ch}:OFFSet?'))
        assert abs(offset+center)<1e-5, ('offset not applied',offset,center)
        assert all(abs(v-center)<3.6*self.scale for v in vals+[lo,hi]), ('invalid/clipped DC',vals,lo,hi)
        return dict(mean_v=float(np.mean(vals)),std_v=float(np.std(vals)),readings_v=vals,
                    min_v=lo,max_v=hi,scale_v=self.scale,offset_v=offset)

    def point(self,f,center=0):
        wanted=20/(12*f); decade=10**math.floor(math.log10(wanted))
        tb=next(v*decade for v in (1,2,5,10) if v*decade>=wanted*(1-1e-9))
        self.write(f':TIMebase:MAIN:SCALe {tb:.12f}')
        self.write(f':CHANnel{self.channel}:OFFSet {-center:.9f}')
        self.write(f':TRIGger:EDGe:LEVel {center:.9f}')
        self.write(':RUN'); self.write(f':ACQuire:MDEPth {self.depth}')

    def capture(self,path,f):
        self.write(':ACQuire:TYPE NORM'); self.write(':RUN'); time.sleep(.4); self.write(':STOP')
        assert self.ask(':TRIGger:STATus?')=='STOP'
        def wave(mode,count):
            self.write(':WAVeform:MODE '+mode); self.write(':WAVeform:STARt 1'); self.write(f':WAVeform:STOP {count}')
            pre=[float(v) for v in self.ask(':WAVeform:PREamble?').split(',')]
            block=self.ask_raw(b':WAVeform:DATA?')
            assert block[:1]==b'#'
            nd=int(block[1:2]); n=int(block[2:2+nd])
            raw=np.frombuffer(block[2+nd:2+nd+n],dtype=np.uint8).copy()
            assert n==len(raw), ('truncated record',n,len(raw))
            return raw, pre
        raw,pre=wave('RAW',self.depth)
        rate=float(self.ask(':ACQuire:SRATe?'))
        screen,spre=wave('NORM',1200)
        np.savez_compressed(path,raw=raw,preamble=pre,screen=screen,screen_preamble=spre,sample_rate_hz=rate)
        assert len(raw)==self.depth and int(pre[2])==self.depth and len(screen)==1200, ('wrong record size',len(raw),pre[2],self.depth,len(screen))
        assert abs(pre[4]*rate-1)<1e-5, ('stale RAW time metadata',pre[4],rate)
        assert abs(float(self.ask(f':CHANnel{self.channel}:SCALe?'))-self.scale)<1e-9
        assert abs(spre[7]/(self.scale/25)-1)<1e-5, ('stale screen gain',spre)
        result=fit_sine(raw,pre,f); normal=fit_sine(screen,spre,f)
        result['screen_fit']=normal
        result['screen_amplitude_difference_v']=normal['vpp_v']-result['vpp_v']
        assert abs(result['screen_amplitude_difference_v'])<.001, ('RAW/screen mismatch',result)
        result['raw_file']=str(path.resolve().relative_to(ROOT))
        return result

    def restore(self):
        # Restore acquisition settings, but retain usable zero-centred displays
        # for the two channels whose old CH4 offset was -5 V.
        self.write(':STOP')
        for k,v in self.prior.items():
            if k==':ACQuire:MDEPth': self.write(':RUN')
            self.write(k+' '+v)
        for ch in (3,4):
            self.write(f':CHANnel{ch}:DISPlay ON'); self.write(f':CHANnel{ch}:COUPling DC')
            self.write(f':CHANnel{ch}:SCALe 0.05'); self.write(f':CHANnel{ch}:OFFSet 0')
        self.write(':TRIGger:SWEep AUTO'); self.write(':RUN')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('stage',choices=['check','tx2','tx3'])
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--resume',type=Path,help='Previous TX3 result with preserved valid acquisitions')
    args=ap.parse_args(); args.out.mkdir(parents=True,exist_ok=False)
    r=dict(started=datetime.now(timezone(timedelta(hours=8))).isoformat(),stage=args.stage,
           connection='TX2 directly to scope CH3; TX3 directly to scope CH4; high impedance coax',
           scope_relative=True,events=[],points=[],status='running')
    agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events'])
    s=None
    def save(): (args.out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    def output(ch,**kw):
        state=agent.call('output',dict(channel=ch,action='start',wiring_confirmed=True,**kw))
        assert state['outputs'][ch]['enabled'] and not state['outputs'][0]['enabled']
        return state
    def sinemeasure(f,zero,peak,label,repeats=2):
        state=output(2,mode='sine_code',frequency_hz=f,offset=zero,peak=peak)
        s.point(f,r.get('diagnostic_center_v',0))
        rows=[]
        for j in range(repeats):
            for attempt in range(3):
                path=args.out/f'{label}_{j}_try{attempt}.npz'
                try:
                    rows.append(s.capture(path,f));break
                except AssertionError as error:
                    r.setdefault('rejected_acquisitions',[]).append(dict(path=str(path),reason=str(error)))
                    save()
                    if attempt==2:raise
                    s.write(f':CHANnel{s.channel}:SCALe {s.scale*2}')
                    s.write(f':CHANnel{s.channel}:SCALe {s.scale}')
                    s.point(f,r.get('diagnostic_center_v',0));time.sleep(1)
        p=dict(frequency_hz=f,zero_code=zero,peak_code=peak,state=state,individual=rows)
        p.update({k:float(np.mean([row[k] for row in rows])) for k in ('vpp_v','dc_v','frequency_hz','thd_2_3','residual_rms_v')})
        p['requested_hz']=f
        p['vpp_std_v']=float(np.std([row['vpp_v'] for row in rows]))
        return p
    try:
        s=Scope(); r.update(scope_idn=s.idn,scope_before=s.prior)
        r['connected']=agent.connect(); r['initialized']=agent.call('initialize',timeout=120)
        assert all(not v['enabled'] for v in r['initialized']['outputs'])
        old=json.loads((ROOT/'data/dac_calibration.json').read_text())
        if args.stage=='check':
            s.setup(4,sine=True,scale=.5)
            z=old['channels'][2]['sine_50mv']['zero_code']
            output(2,mode='sine_code',frequency_hz=100000,offset=z,peak=400)
            r['wide_check']=s.dc(0)
            r['diagnostic_center_v']=round(r['wide_check']['mean_v'],2)
            save();print('TX3 wide check '+json.dumps(r['wide_check']),flush=True)
            s.setup(4,sine=True,scale=.02)
            for f,zero in [(100000,z),(100000,z-160),(10000,z),(1000000,z),(6000000,z)]:
                p=sinemeasure(f,zero,400,'check'+str(len(r['points'])))
                r['points'].append(p);save()
                print(json.dumps({k:p[k] for k in ('requested_hz','zero_code','vpp_v','dc_v','thd_2_3')}),flush=True)
            a,b=r['points'][:2]
            slope=(a['dc_v']-b['dc_v'])/160
            assert .00002<slope<.0002, slope
            r['zero_slope_v_per_code']=slope
            r['zero_code']=round(z-a['dc_v']/slope)
            read_scope('169.254.1.5',4,args.out/'tx3_6mhz',r['connection'],scope=s.s)
        elif args.stage=='tx2':
            s.setup(3)
            # Measure 37 knots at 50 mV spacing, verify every knot and its
            # 25 mV midpoint independently, then express the result in the
            # application's existing 10 mV table format by interpolation.
            oldcodes=old['channels'][1]['dc_table']['codes'][::5]
            for i,code in enumerate(oldcodes):
                target=i*.05
                state=output(1,mode='dc_code',offset=code)
                p=dict(target_v=target,code=code,measurement=s.dc(target),state=state)
                r['points'].append(p);save()
                if i%5==0: print(f'baseline {i+1}/37 target={target:.2f} measured={p["measurement"]["mean_v"]:.6f}',flush=True)
            volts=np.array([p['measurement']['mean_v'] for p in r['points']])
            assert np.all(np.diff(volts)>.005), 'Nonmonotonic DC transfer'
            codes=np.array(oldcodes)
            def inverse(v):
                i=min(max(int(np.searchsorted(volts,v))-1,0),len(volts)-2)
                return round(codes[i]+(v-volts[i])/(volts[i+1]-volts[i])*(codes[i+1]-codes[i]))
            candidate=[inverse(i*.05) for i in range(37)]
            r['correction']=[]
            for i in range(37):
                code=candidate[i]; target=i*.05
                attempts=[]
                for attempt in range(3):
                    state=output(1,mode='dc_code',offset=code)
                    m=s.dc(target); error=m['mean_v']-target
                    attempts.append(dict(code=code,measurement=m,error_v=error))
                    if abs(error)<=.0005: break
                    if attempt<2: code=round(code+error/.000060)
                assert abs(error)<.001, ('DC correction failed',target,error)
                candidate[i]=code
                r['correction'].append(dict(target_v=target,code=code,attempts=attempts,state=state));save()
                if i%5==0: print(f'corrected {i+1}/37 target={target:.2f} error_mV={error*1000:.3f}',flush=True)
            assert all(a>b for a,b in zip(candidate,candidate[1:])), 'Nonmonotonic corrected codes'
            r['measured_knot_step_v']=.05;r['candidate_knot_codes']=candidate
            table=[round(float(np.interp(i*.01,np.arange(37)*.05,candidate))) for i in range(181)]
            r['candidate_codes']=table; r['verification']=[]
            for i in range(72,-1,-1):
                target=i*.025; code=round(float(np.interp(target,np.arange(181)*.01,table)))
                output(1,mode='dc_code',offset=code)
                m=s.dc(target); error=m['mean_v']-target
                r['verification'].append(dict(target_v=target,code=code,measurement=m,error_v=error));save()
                if i%5==0: print(f'verify {73-i}/73 target={target:.3f} error_mV={error*1000:.3f}',flush=True)
            r['max_verification_error_v']=max(abs(p['error_v']) for p in r['verification'])
            r['verified']=r['max_verification_error_v']<.0015
            read_scope('169.254.1.5',3,args.out/'tx2_zero_verified',r['connection'],scope=s.s)
        elif args.stage=='tx3':
            # A large DC displacement needs a measured local transfer rather
            # than a small difference easily confused with warm-up drift.
            previous={}
            if args.resume:
                previous=json.loads(args.resume.read_text())
                assert previous['close']['cleanup_confirmed']
                assert previous['initialized']['identity']['bit_sha256']==r['initialized']['identity']['bit_sha256']
                z=previous['zero_code'];slope=previous['zero_slope_v_per_code']
                r.update(resume_source=str(args.resume),points=previous['points'],
                         zero_transfer=previous['zero_transfer'],zero_refinement=previous['zero_refinement'])
            else:
                r['zero_transfer']=[]
                for z in (32404,30404):
                    s.setup(4,sine=True,scale=.5)
                    output(2,mode='sine_code',frequency_hz=100000,offset=z,peak=290)
                    wide=s.dc(0)
                    r['diagnostic_center_v']=round(wide['mean_v'],2)
                    s.setup(4,sine=True,scale=.02)
                    p=sinemeasure(100000,z,290,'transfer'+str(z),repeats=3)
                    p['wide_check']=wide;r['zero_transfer'].append(p);save()
                a,b=r['zero_transfer'];slope=(a['dc_v']-b['dc_v'])/2000
                assert .00002<slope<.0002,slope
                z=round(a['zero_code']-a['dc_v']/slope)
                assert 1000<z<64535,z
                r['diagnostic_center_v']=0
                s.setup(4,sine=True,scale=.02)
                r['zero_refinement']=[]
                for i in range(4):
                    p=sinemeasure(100000,z,290,'zero'+str(i),repeats=3)
                    r['zero_refinement'].append(p);save()
                    print(f'TX3 zero code={z} measured={p["dc_v"]*1000:.3f}mV',flush=True)
                    if abs(p['dc_v'])<.0005:break
                    if i<3:z=round(z-p['dc_v']/slope)
                assert abs(p['dc_v'])<.002,('Unstable TX3 zero',p['dc_v'])
            r['zero_code']=z; r['zero_slope_v_per_code']=slope
            s.setup(4,sine=True)
            frequencies=old['channels'][2]['sine_50mv']['frequency_hz']
            peaks=[]
            for i,f in enumerate(frequencies):
                if i<len(previous.get('points',[])):
                    p=previous['points'][i];assert p['requested_hz']==f
                else:
                    p=sinemeasure(f,z,290,'baseline'+str(i)); r['points'].append(p)
                assert .035<p['vpp_v']<.07 and p['thd_2_3']<.05, ('Abnormal sine',p)
                peaks.append(round(290*.05/p['vpp_v'])); save()
                if i%5==0: print(f'baseline {i+1}/78 {f}Hz {p["vpp_v"]*1000:.4f}mVpp DC={p["dc_v"]*1000:.3f}mV',flush=True)
            r['candidate_peaks']=peaks; r['frequency_hz']=frequencies; r['verification']=previous.get('verification',[])
            for i in range(len(frequencies)-1,-1,-1):
                if any(p['requested_hz']==frequencies[i] for p in r['verification']):continue
                p=sinemeasure(frequencies[i],z,peaks[i],'verify'+str(i));p['error_v']=p['vpp_v']-.05
                r['verification'].append(p);save()
                if i%5==0: print(f'verify {78-i}/78 {frequencies[i]}Hz error={p["error_v"]*1000:.4f}mV DC={p["dc_v"]*1000:.3f}mV',flush=True)
            r['midpoints']=previous.get('midpoints',[])
            for f in [15000,55000,155000,250000,450000,950000,1550000,2550000,3550000,4550000,5550000,5950000]:
                if any(p['requested_hz']==f for p in r['midpoints']):continue
                peak=float(np.interp(f,frequencies,peaks))
                p=sinemeasure(f,z,peak,'mid'+str(f));p['error_v']=p['vpp_v']-.05
                r['midpoints'].append(p);save()
            checked=r['verification']+r['midpoints']
            r['max_vpp_error_v']=max(abs(p['error_v']) for p in checked)
            r['max_dc_error_v']=max(abs(p['dc_v']) for p in checked)
            r['verified']=r['max_vpp_error_v']<.00075 and r['max_dc_error_v']<.002
            read_scope('169.254.1.5',4,args.out/'tx3_verified',r['connection'],scope=s.s)
        r['status']='completed';save()
    except BaseException as e:
        r['error']=repr(e);r['status']='failed';raise
    finally:
        try: r['close']=agent.close()
        except Exception as e:r['cleanup_error']=repr(e)
        if s:
            try:s.restore();r['scope_restored_with_zero_centered_ch3_ch4']=True
            except Exception as e:r['scope_restore_error']=repr(e)
            try:s.s.close()
            except Exception as e:r['scope_close_error']=repr(e)
        r['ended']=datetime.now(timezone(timedelta(hours=8))).isoformat();save()
        print(json.dumps({k:v for k,v in r.items() if k in ('status','error','close','cleanup_error','verified','zero_code','max_verification_error_v','max_vpp_error_v','max_dc_error_v')},indent=2),flush=True)


if __name__=='__main__':main()
