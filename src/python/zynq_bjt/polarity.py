"""Bounded, two-polarity probe; weak conduction alone never establishes PNP."""
from dataclasses import dataclass, asdict
from pathlib import Path
import csv
import json
import math
import statistics
import time
import uuid

from .profiles import Profile

PROBE_RC_OHM = 50.0


@dataclass(frozen=True)
class ProbeConfig:
    profile: str = 'npn_small'
    vcc_v: float = 1.0
    base_currents_ua: tuple = (10.0, 30.0, 100.0)
    base_resistance_ohm: float = 2000.0
    collector_resistor_ohm: float = PROBE_RC_OHM
    collector_channel: int = 1
    source_channel: int = 0
    collector_adc_per_v: float = .206
    source_adc_per_v: float = .206
    settle_s: float = .1
    frames_per_point: int = 3
    max_current_a: float = .02
    min_delta_current_a: float = .0001
    min_gain: float = 3.0
    dominance_ratio: float = 3.0
    max_node_drift_v: float = .03

    def validate(self, calibration, front):
        Profile(self.profile)
        if self.collector_resistor_ohm != PROBE_RC_OHM: raise ValueError('自动识别固定使用小功率档，RC=50 Ω')
        if not .2 <= self.vcc_v <= 1.2: raise ValueError('识别电源范围为 0.2～1.2 V')
        if len(self.base_currents_ua)!=3 or any(not math.isfinite(v) or not 10<=v<=100 for v in self.base_currents_ua):
            raise ValueError('识别使用三个 10～100 μA 小电流点')
        if list(self.base_currents_ua)!=sorted(set(self.base_currents_ua)): raise ValueError('识别电流必须递增且不重复')
        for key in ('base_resistance_ohm','collector_resistor_ohm','collector_adc_per_v','source_adc_per_v',
                    'min_delta_current_a','min_gain','dominance_ratio','max_node_drift_v'):
            if not math.isfinite(getattr(self,key)) or getattr(self,key)<=0: raise ValueError('识别换算和阈值须为正的有限数值')
        if self.dominance_ratio<2: raise ValueError('正反向响应比至少为 2')
        if type(self.frames_per_point) is not int or not 2<=self.frames_per_point<=10: raise ValueError('每点采集 2～10 帧')
        if not math.isfinite(self.settle_s) or not 0<=self.settle_s<=2: raise ValueError('识别等待范围为 0～2 秒')
        if not math.isfinite(self.max_current_a) or not .0001<=self.max_current_a<=.02: raise ValueError('识别电流截止阈值为 0.1～20 mA')
        if {self.collector_channel,self.source_channel}!={0,1}: raise ValueError('两路反馈须使用不同 ADC')
        codes=[calibration.dac_code(0,v*1e-6*self.base_resistance_ohm)[0] for v in (0,)+tuple(self.base_currents_ua)]
        if len(set(codes))!=4: raise ValueError('识别电流步进小于 DAC 码分辨率')
        calibration.dac_code(1,front.tx2_for_uce(self.vcc_v))
        return self


def classify(points, config):
    evidence={}
    for polarity in ('npn','pnp'):
        rows=[p for p in points if p['polarity']==polarity]
        if len(rows)!=4: return dict(polarity='unknown',reason='测试点不足',evidence=evidence)
        baseline=rows[0]['ic_a'];driven=rows[1:]
        noise=max(p['noise_current_a'] for p in rows)
        delta=max(p['ic_a']-baseline for p in driven)
        threshold=max(config.min_delta_current_a,noise*4)
        monotonic=all(b['ic_a']>=a['ic_a']-threshold for a,b in zip(rows,rows[1:]))
        score=max(0.0,delta)/max(p['ib_estimated_a'] for p in driven)
        eligible=(delta>threshold and score>=config.min_gain and monotonic
                  and abs(baseline)<max(threshold,delta*.25))
        evidence[polarity]=dict(baseline_a=baseline,delta_a=delta,threshold_a=threshold,
                                response_gain=score,eligible=eligible,monotonic=monotonic)
    winner=max(evidence,key=lambda k:evidence[k]['response_gain'])
    loser='pnp' if winner=='npn' else 'npn'
    ratio=evidence[winner]['response_gain']/max(evidence[loser]['response_gain'],1.0)
    valid=evidence[winner]['eligible'] and ratio>=config.dominance_ratio
    return dict(polarity=winner if valid else 'unknown',dominance_ratio=ratio,evidence=evidence,
                reason='两种接法的增量响应达到区分阈值' if valid else '响应过弱、漏电过大或两种接法差异不足；请检查接线并人工确认')


def run_probe(board, calibration, front, config, output_root, cancel, emit=lambda *args:None):
    config.validate(calibration,front)
    from .result_paths import create_run
    directory=create_run(output_root,config.profile,'detect')
    simulated=bool(getattr(board,'simulated',False))
    state=dict(measurement='polarity',status='running',profile=config.profile,simulated=simulated,
               config=asdict(config),frontend=asdict(front),started_at=time.time(),points=0,cleanup_errors=[],
               classification=dict(polarity='unknown',reason='识别进行中'),
               limitation='Empirical low-bias two-route response test; not a pinout, power-rating or device-health certification')
    points=[];seen=set();original_transfer=getattr(board,'measurement_transfer',None)
    def save():
        temp=directory/'run.json.tmp';temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(directory/'run.json')
    def pause(seconds):
        if cancel.wait(seconds):raise InterruptedError('识别已取消')
    def mute():
        errors=[]
        for ch in range(3):
            try:
                if board.enable(ch,False).enabled:raise RuntimeError('输出未关闭')
            except Exception as exc:errors.append('TX{}: {}'.format(ch+1,exc))
        if errors:raise RuntimeError('; '.join(errors))
    def sense(polarity,step,ib,route,raw,expected):
        frames=[]
        for repeat in range(config.frames_per_point+1):
            pause(0)
            gpio=board.gpio()
            if gpio['output']!=route or (gpio['output']^gpio['sense'])&127:raise RuntimeError('识别期间继电器回读改变')
            for ch,code in enumerate(expected):
                output=board.output(ch)
                if not output.enabled or output.code!=code:raise RuntimeError('识别期间激励输出状态改变')
            frame=board.capture()
            raw.write(json.dumps(dict(polarity=polarity,index=step,repeat=repeat,discarded=repeat==0,frame=frame.as_record()))+'\n');raw.flush()
            if frame.simulated!=simulated or frame.sequence in seen:raise ValueError('采样来源或帧序号异常')
            seen.add(frame.sequence)
            codes=[statistics.fmean(frame.codes(ch)) for ch in (0,1)]
            if any(frame.overrange(ch) or min(frame.codes(ch))==0 or max(frame.codes(ch))==65535 for ch in (0,1)):
                raise ValueError('识别 ADC 过量程或削顶')
            if not simulated and any(abs(rate-50e6)>1e6 for rate in frame.sample_rates_hz):raise ValueError('识别 ADC 时钟异常')
            ports=[calibration.port_v(codes[ch],ch) for ch in (0,1)]
            supply=ports[config.source_channel]/config.source_adc_per_v
            node=ports[config.collector_channel]/config.collector_adc_per_v
            current=(supply-node)/config.collector_resistor_ohm
            if abs(current)>config.max_current_a:raise ValueError('识别电流超过截止阈值 {:.3g} A'.format(config.max_current_a))
            if abs(supply-config.vcc_v)>max(.15,config.vcc_v*.25):raise ValueError('识别电源反馈与设定不符')
            if repeat:frames.append(dict(codes=codes,ports=ports,vcc_v=supply,node_v=node,ic_a=current))
        if any(max(p[key] for p in frames)-min(p[key] for p in frames)>config.max_node_drift_v for key in ('node_v','vcc_v')):
            raise ValueError('识别反馈尚未稳定')
        profiles=(calibration.rx1,calibration.rx2)
        quantization=math.hypot(abs(profiles[config.source_channel]['slope_nv_per_code'])/1e9/config.source_adc_per_v,
                                abs(profiles[config.collector_channel]['slope_nv_per_code'])/1e9/config.collector_adc_per_v)/config.collector_resistor_ohm
        row=dict(polarity=polarity,index=step,ib_estimated_a=ib,rx1_mean_code=statistics.fmean(p['codes'][0] for p in frames),
                 rx2_mean_code=statistics.fmean(p['codes'][1] for p in frames),rx1_port_v=statistics.fmean(p['ports'][0] for p in frames),
                 rx2_port_v=statistics.fmean(p['ports'][1] for p in frames),
                 noise_current_a=max(quantization,statistics.pstdev(p['ic_a'] for p in frames)),gpio=route)
        row.update({key:statistics.fmean(p[key] for p in frames) for key in ('vcc_v','node_v','ic_a')})
        return row
    save()
    try:
        with (directory/'frames.jsonl').open('w',encoding='utf-8') as raw:
            for polarity in ('npn','pnp'):
                pause(0);mute()
                # Probe every device using the small-power fixture and 50-ohm RC.
                key=polarity+'_small'
                route=Profile(key).route('output')['value']
                board.gpio(127,route)
                pause(max(.05,config.settle_s))
                if simulated and hasattr(board,'set_measurement_transfer'):
                    board.set_measurement_transfer(dict(profile=key,polarity_probe=True,base_resistance_ohm=config.base_resistance_ohm,
                        collector_resistor_ohm=config.collector_resistor_ohm,collector_channel=config.collector_channel,
                        source_channel=config.source_channel,collector_adc_per_v=config.collector_adc_per_v,source_adc_per_v=config.source_adc_per_v))
                base_code=calibration.dac_code(0,0)[0];supply_code=calibration.dac_code(1,front.tx2_for_uce(config.vcc_v))[0]
                board.set_code(0,base_code);board.set_code(1,supply_code)
                board.enable(1,True);board.enable(0,True)
                for index,current_ua in enumerate((0,)+tuple(config.base_currents_ua)):
                    pause(0)
                    base_code,actual=calibration.dac_code(0,current_ua*1e-6*config.base_resistance_ohm)
                    board.set_code(0,base_code);pause(config.settle_s)
                    row=sense(polarity,index,actual/config.base_resistance_ohm,route,raw,(base_code,supply_code))
                    points.append(row);state['points']=len(points);save();emit('probe_point',row)
            state['classification']=classify(points,config);state['status']='complete'
    except Exception as exc:
        state['status']='cancelled' if isinstance(exc,InterruptedError) else 'failed';state['error']=str(exc)
    finally:
        try:mute()
        except Exception as exc:state['cleanup_errors'].append(str(exc))
        try:
            state['final_gpio']=board.gpio(127,0)
            if state['final_gpio']['output']&127 or state['final_gpio']['sense']&127:raise RuntimeError('GPIO 复位回读不一致')
        except Exception as exc:state['cleanup_errors'].append('GPIO: '+str(exc))
        if simulated and hasattr(board,'set_measurement_transfer'):board.set_measurement_transfer(original_transfer)
        if state['cleanup_errors']:
            state['status']='cleanup_failed';state['classification'].update(polarity='unknown',reason='输出或 GPIO 清理未确认')
        if points:
            with (directory/'points.csv').open('w',newline='',encoding='utf-8-sig') as stream:
                writer=csv.DictWriter(stream,fieldnames=tuple(points[0]));writer.writeheader();writer.writerows(points)
        state['finished_at']=time.time();save()
    return dict(directory=str(directory),relative_directory=directory.relative_to(output_root).as_posix(),run_id=directory.name,state=state,files=[p.name for p in directory.iterdir() if p.is_file()])
