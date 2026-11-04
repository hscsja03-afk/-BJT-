"""LCD shares the desktop transport; no second login or hardware owner."""
import base64
import hashlib
import math
import threading
import time
import zlib
import uuid
import tkinter as tk
from copy import copy
from .lcd import LcdDemo,frame_pixels
from .lcd_records import make_plot, fit_limits, load_latest
from .desktop_output import prepare
from .scope_display import reference_channels


class SharedTransport:
    """Serialize LCD traffic with commands; cancellation bypasses the lock."""
    def __init__(self, transport):
        self.inner=transport
        self.command_lock=threading.Lock()
        self.waiting=0

    def __getattr__(self,name):return getattr(self.inner,name)

    def call(self,*args,**kwargs):
        self.waiting+=1
        try:
            with self.command_lock:return self.inner.call(*args,**kwargs)
        finally:self.waiting-=1

    def close(self):
        with self.command_lock:return self.inner.close()

    def try_lcd(self,request):
        if self.waiting:return None
        if not self.command_lock.acquire(blocking=False):return None
        try:return self.inner.call('lcd',request,timeout=30)
        finally:self.command_lock.release()

    def stream_lcd(self,request):
        # This protocol operation only replaces a mailbox. It cannot touch
        # outputs, GPIO or MMIO, and does not queue behind the long scan RPC.
        return self.inner.call('lcd_stream',request,timeout=30)


class DesktopLcd:
    def __init__(self,app):
        self.app=app
        self.model=LcdDemo();self.model.live=True
        self.enabled=tk.BooleanVar(value=True)
        self.status=tk.StringVar(value='LCD：初始化后自动联动')
        self.generation=0;self.inflight=False;self.failed=False
        self.last_hash=None;self.last_upload=0;self.buttons=[]
        self.last_status=None;self.last_frame=None;self.drop_touch=True
        self.last_bjt=None
        self.pending_action=None
        self.remaining=0;self.upload_digest=None;self.upload_buttons=[];self.last_render=0
        self.exchange_count=0;self.frames_completed=0
        self.stream_id=None
        panel=app.pages['settings']
        bar=tk.Frame(panel,bg='#101827');bar.pack(side='bottom',fill='x',padx=12,pady=5)
        tk.Checkbutton(bar,text='LCD 联动',variable=self.enabled,command=self.changed,
                       bg='#101827',fg='#e8f0ff',selectcolor='#20354d').pack(side='left')
        app.label(bar,textvariable=self.status).pack(side='left',padx=12)
        self.job=app.root.after(100,self.tick)

    def changed(self):
        self.generation+=1;self.drop_touch=True;self.last_hash=None;self.failed=False;self.pending_action=None
        self.remaining=0;self.upload_digest=None;self.last_render=0
        self.status.set('LCD：等待联动' if self.enabled.get() else 'LCD：联动已暂停')

    def connected(self):
        self.changed();self.last_status=None;self.last_frame=None;self.buttons=[]

    def ready(self):
        app=self.app
        return bool(self.enabled.get() and not self.failed and not app.closing and
                    isinstance(app.transport,SharedTransport) and app.transport.alive and
                    not app.transport.simulated and (app.last_status or {}).get('initialized'))

    def before_job(self,op):
        # A touch sampled before another command must not change its settings.
        if op not in ('capture','meter'):
            self.generation+=1;self.drop_touch=True;self.pending_action=None
            self.remaining=0;self.upload_digest=None;self.last_hash=None;self.last_render=0
        if not self.ready() or op not in ('scan','probe','identify','detect','retrieve','disconnect'):
            return None
        model=self.model
        note=model.note
        model.note='测量中，触摸暂停；停止请用上位机' if op!='disconnect' else '上位机正在断开连接'
        try:pixels=frame_pixels(model.render())
        finally:model.note=note
        self.last_hash=None
        return dict(pixels=base64.b64encode(zlib.compress(pixels,1)).decode(),incremental=True,max_writes=8192,native=model.native,pixel_format='rgb565' if model.rgb565 else 'indexed4')

    def begin_scan(self,request):
        self.stream_id=None
        app=self.app
        if (not self.enabled.get() or self.failed or app.closing
                or not isinstance(app.transport,SharedTransport) or not app.transport.alive
                or app.transport.simulated):return
        self.sync()
        self.model.page='BJT'
        self.model.has_data=False;self.model.saved_plot=None
        self.model.note='扫描中 · 等待首个测点'
        self.stream_id=uuid.uuid4().hex
        request['lcd_stream']=dict(id=self.stream_id,
            native=self.model.native if (app.last_status or {}).get('initialized') else None)
        self.bjt_current()

    def sync(self):
        app=self.app;m=self.model;state=app.last_status or {}
        m.native=bool(state.get('lcd_native',False))
        m.rgb565=bool(state.get('lcd_rgb565',False))
        m.running=app.scope.accepting
        try:
            m.sample_count=int(app.scope.sample_count.get())
            if app.scope.sample_stride.get()!='自动窗口':m.sample_stride=int(app.scope.sample_stride.get())
        except ValueError:pass
        setting=state.get('output_settings',{}).get(str(m.tx),{})
        supported=(setting.get('display_unit')=='voltage' and
                   ((m.tx!=2 and setting.get('display_waveform')=='dc') or
                    (m.tx==2 and setting.get('display_waveform') in ('sine','square','triangle') and
                     float(setting.get('display_offset',0))==0)))
        m.tx_preview_hidden=bool(state.get('outputs') and state['outputs'][m.tx]['enabled'] and not supported)
        if state is not self.last_status:
            self.last_status=state
            m.enabled=[s['enabled'] for s in state.get('outputs',[dict(enabled=False)]*3)]
            m.gpio=state.get('gpio',{}).get('output',0)
            for key,s in state.get('output_settings',{}).items():
                channel=int(key)
                wave=s.get('display_waveform')
                if s.get('display_unit')=='voltage':
                    value=s.get('display_peak' if channel==2 and wave!='dc' else 'display_offset')
                    if value is not None:m.volts[channel]=abs(float(value)) if channel==2 else float(value)
                    if channel==2 and wave in ('sine','square','triangle'):
                        m.wave=wave;m.frequency=float(s['frequency_hz'])
        frame=app.last_frame
        frame_key=(id(frame),app.scope.raw)
        if m.page=='RX' and frame is None and self.last_frame is not None:
            self.last_frame=None;m.rx_trace=None;m.has_data=False;m.note='等待采集'
        if m.page=='RX' and frame is not None and frame_key!=self.last_frame:
            self.last_frame=frame_key
            channels=app.scope.converted if app.scope.frame is frame else reference_channels(frame,app.scope_calibration)
            raw=app.scope.raw
            m.rx_units='ADC 码' if raw else '电压 / V'
            if not raw and any(c['overrange'] or not all(math.isfinite(v) for v in c['reference_volts']) for c in channels):
                m.rx_trace=None;m.has_data=False;m.note='RX过量程，检查输入'
            else:
                m.rx_trace=[[(i/rate*1e6,v) for i,v in enumerate(c['codes'] if raw else c['reference_volts'])]
                            for c,rate in zip(channels,frame['sample_rates_hz'])]
                m.has_data=True;m.sample_count=len(frame['words'][0]);m.sample_stride=frame.get('sample_stride',1)
                m.note=f"{frame['sample_rates_hz'][0]/1e6:.3g} MS/s · {m.sample_count} 点"

    def page(self,name):
        mapping={'tx':'TX','scope':'RX','meter':'RX','gpio':'IO',
                 'input':'BJT','output':'BJT','beta':'BJT','ac':'BJT'}
        if name not in mapping:return
        self.model.action(mapping[name]);self.last_frame=None;self.last_hash=None
        self.remaining=0;self.upload_digest=None;self.last_render=0
        if mapping[name]=='BJT':
            p=self.app.selected_profile();self.model.pnp=p.pnp;self.model.big=p.big
            self.model.mode={'input':'输入','output':'输出','beta':'β','ac':'交流'}[name]
            self.bjt_current()
        self.generation+=1;self.drop_touch=True

    def bjt_current(self):
        try:self._bjt_current()
        except Exception as exc:
            self.model.has_data=False;self.model.note='LCD曲线暂不可用'
            self.app.log('LCD曲线：'+str(exc))

    def _bjt_current(self):
        app=self.app;m=self.model
        if m.page!='BJT':return
        from .lcd_records import MODES
        if MODES[m.mode]!=app.measurement:m.mode={'input':'输入','output':'输出','beta':'β','ac':'交流'}[app.measurement]
        profile=app.selected_profile();m.pnp=profile.pnp;m.big=profile.big
        scanning=app.busy and getattr(app,'active_job',None)=='scan'
        if not app.rows:
            m.has_data=False;m.saved_plot=None
            m.note='扫描中 · 等待首个测点' if scanning else '等待测量'
            return
        state=(app.last_result or {}).get('state',dict(simulated=bool(app.transport and app.transport.simulated),
            status='running' if scanning else '当前测点',config=dict(profile=profile.key)))
        plot=make_plot(app.rows,state,m.mode)
        if m.mode in ('交流','Rin') and app.ac_history.record and app.ac_history.eligible() and app.ac_history.mode.get()!='本次采集':
            ref=app.ac_history.visible_record(app.rows)
            series=ref.get('series' if m.mode=='交流' else 'rin_series',[])
            selected=[s for s in series if s['label'].startswith('sweep' if m.mode=='交流' else 'input resistance')]
            plot['curves']=[([(float(x)/1000,float(y)) for x,y in s['points']],c) for s,c in zip(selected,(6,7,9,14))]
            plot['label']='历史参考 · '+ref['id']
        fit_limits(plot);m.saved_plot=plot;m.has_data=True
        m.note=('扫描中 · {} 个测点 · 停止请用上位机'.format(len(app.rows)) if scanning else '上位机当前曲线')

    def tick(self):
        self.job=self.app.root.after(30 if self.model.rgb565 else 100,self.tick)
        app=self.app
        streaming=bool(app.busy and getattr(app,'active_job',None)=='scan' and self.stream_id)
        if not self.ready() or (app.busy or app.queue_reserved()) and not streaming or self.inflight:return
        try:
            self.sync()
            if streaming:self.bjt_current()
            interval=.1 if self.model.rgb565 else .25
            render=(streaming or not self.remaining) and time.monotonic()-self.last_render>=interval
            if streaming and not render:return
            model=copy(self.model)
            model.volts=list(self.model.volts);model.enabled=list(self.model.enabled)
            last_hash=self.last_hash
            if render:self.last_render=time.monotonic()
            transport=app.transport;generation=self.generation;stream_id=self.stream_id
            self.inflight=True
            def work():
                request=dict(incremental=True,max_writes=8192,native=model.native,pixel_format='rgb565' if model.rgb565 else 'indexed4');digest=None;buttons=[]
                try:
                    if render:
                        pixels=frame_pixels(model.render());digest=hashlib.sha256(pixels).hexdigest();buttons=list(model.buttons)
                        if digest!=last_hash:request['pixels']=base64.b64encode(zlib.compress(pixels,1)).decode()
                    if streaming:
                        request['stream_id']=stream_id
                        value=transport.stream_lcd(request) if 'pixels' in request else None
                    else:value=transport.try_lcd(request)
                    error=None
                except Exception as exc:value=None;error=str(exc)
                app.events.put(('lcd_reply',None,dict(value=value,error=error,transport=transport,
                    generation=generation,digest=digest,buttons=buttons,uploaded='pixels' in request)))
            threading.Thread(target=work,daemon=True).start()
        except Exception as exc:
            self.failed=True;self.status.set('LCD：'+str(exc));app.log('LCD 联动暂停：'+str(exc))

    def reply(self,result):
        self.inflight=False;app=self.app
        if result['transport'] is not app.transport:return
        if result['error']:
            self.failed=True;self.status.set('LCD：联动异常，可重新勾选重试')
            app.log('LCD 联动暂停：'+result['error']);return
        if result['value'] is None:return
        self.exchange_count+=1
        if result['value'].get('stream'):
            if result['generation']==self.generation and result['value'].get('accepted'):
                self.last_hash=result['digest'];self.remaining=0
                self.status.set('LCD：扫描曲线同步中')
            self.drop_touch=True
            return
        stale=result['generation']!=self.generation or app.queue_reserved() or not self.enabled.get()
        previous=self.buttons
        self.remaining=result['value'].get('remaining',0)
        if result['uploaded']:
            self.upload_digest=result['digest'];self.upload_buttons=result['buttons']
            self.last_upload=time.monotonic()
        if not self.remaining and self.upload_digest is not None:
            self.last_hash=self.upload_digest if not stale else None
            self.buttons=self.upload_buttons if not stale else []
            self.upload_digest=None;self.frames_completed+=1
        if stale:
            self.last_hash=None;self.upload_digest=None;self.remaining=0
            return
        self.status.set('LCD：共用当前连接 · 已联动')
        touch=result['value'].get('touch')
        discard=self.drop_touch or (self.remaining>0 and self.upload_buttons!=self.buttons) or previous!=self.buttons
        if not self.remaining:self.drop_touch=False
        if touch and not discard:
            x,y=touch
            action=next((action for box,action in self.buttons if box[0]<=x/2<box[2] and box[1]<=y/2<box[3]),None)
            if action:
                if app.busy and getattr(app,'active_job',None) in ('capture','meter'):
                    self.pending_action=(self.generation,action)
                elif not app.busy:self.action(action)

    def drain_touch(self):
        pending,self.pending_action=self.pending_action,None
        if pending and pending[0]==self.generation and not self.app.busy:
            self.action(pending[1])

    def action(self,action):
        app=self.app;m=self.model
        if app.busy or app.queue_reserved() or not self.ready():return
        if action=='stop':app.stop();return
        self.generation+=1
        try:
            if action=='RX':app.show_page('scope');return
            if action=='TX':app.show_page('tx');return
            if action=='IO':app.show_page('gpio');return
            if action=='BJT':app.show_page(app.measurement);return
            if m.page=='TX' and m.tx_preview_hidden and action in ('minus','plus','wave','frequency'):
                raise ValueError('此输出参数请在上位机修改')
            if m.page=='RX' and action in ('single','run'):
                if action=='run' and app.scope.accepting:app.scope.stop()
                else:
                    app.scope.single() if action=='single' else app.scope.run()
                return
            m.action(action)
            if action.startswith('io'):
                bit=1<<int(action[2:]);app.submit('gpio',dict(mask=bit,value=m.gpio));return
            if m.page=='TX' and action in ('power','minus','plus','wave','frequency'):
                channel=m.tx
                if action=='power' and not m.enabled[channel]:
                    app.submit('output',dict(channel=channel,action='stop'));return
                if m.enabled[channel]:
                    plan=prepare(channel,m.wave if channel==2 else 'dc','voltage',
                         dict(offset=0 if channel==2 else m.volts[channel],peak=m.volts[channel] if channel==2 else 0,
                              frequency_hz=m.frequency,phase_degrees=0,duty_percent=50),app.scope_calibration,
                         confirmed=app.confirmed.get(),action='start')
                    app.submit('output',plan['request'])
                else:m.note='待启动设定'
            elif m.page=='BJT' and action in ('single','polarity','size','mode'):
                profile=('pnp' if m.pnp else 'npn')+('_big' if m.big else '_small')
                m.has_data=False;m.saved_plot=None
                m.saved_plot=load_latest(app.results,app.data,profile,m.mode);m.has_data=True;m.note='已保存曲线'
            elif m.page=='RX' and action in ('points','stride'):
                app.scope.stop();app.scope.sample_count.set(str(m.sample_count));app.scope.sample_stride.set(str(m.sample_stride))
                m.has_data=False;m.note='采集参数已同步'
        except Exception as exc:
            m.note=str(exc)[:35];app.log('LCD：'+str(exc))
        finally:
            self.last_status=None;self.sync()

    def close(self):
        self.generation+=1
        if self.job is not None:self.app.root.after_cancel(self.job);self.job=None
