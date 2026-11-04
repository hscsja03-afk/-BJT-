"""PC渲染、UART传屏和触摸控制；需要LCD新版位流与匹配agent。"""
import argparse,base64,json,sys,time,zlib
from pathlib import Path
from tx2_scope_zero import ROOT,SerialAgent
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.lcd import LcdDemo
from zynq_bjt.frontend import Calibration
from zynq_bjt.scope_display import reference_channels,finite
from zynq_bjt.desktop_output import prepare
from zynq_bjt.lcd_records import load_latest

ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True)
ap.add_argument('--seconds',type=float,default=0);ap.add_argument('--allow-tx12',action='store_true')
ap.add_argument('--bitfile');ap.add_argument('--report',type=Path,required=True);args=ap.parse_args()
model=LcdDemo();model.live=True;cal=Calibration(args.base/'data');r={'events':[],'actions':[],'running':False}
stop_file=ROOT/'report/lcd_update_20261102/stop.request'
args.report.parent.mkdir(parents=True,exist_ok=True)

def checkpoint():
 r['updated_at']=time.time()
 temporary=args.report.with_suffix('.tmp')
 temporary.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
 temporary.replace(args.report)
a=SerialAgent('COM7','xilinx',r['events'],base=args.base,bitfile=args.bitfile);start=time.monotonic();initialized=False
def upload():
 image=model.render()
 encoded=base64.b64encode(zlib.compress(image.tobytes())).decode()
 result=a.call('lcd',dict(pixels=encoded),timeout=30)
 r['uploaded_frames']=r.get('uploaded_frames',0)+1;r['page']=model.page
 image.resize((1024,600),resample=0).save(args.report.parent/'last_frame.png')
 return result
def capture():
 model.has_data=False;model.rx_trace=None
 frame=a.call('capture',dict(sample_count=model.sample_count,sample_stride=model.sample_stride),timeout=30)
 converted=reference_channels(frame,cal)
 if any(ch['overrange'] or not all(finite(v) for v in ch['reference_volts']) for ch in converted):
  model.has_data=False;model.rx_trace=None;raise ValueError('RX过量程或换算无效')
 model.rx_trace=[[(i/rate*1e6,v) for i,v in enumerate(ch['reference_volts'])]
                 for ch,rate in zip(converted,frame['sample_rates_hz'])]
 model.has_data=True;r['last_capture']=dict(sequence=frame['sequence'],simulated=frame['simulated'])
 model.note=f"{frame['sample_rates_hz'][0]/1e6:.3g} MS/s · {model.sample_count} 点"
def saved():
 model.has_data=False;model.saved_plot=None
 profile=('pnp' if model.pnp else 'npn')+('_big' if model.big else '_small')
 model.saved_plot=load_latest(ROOT/'measurements/results',args.base/'data',profile,model.mode)
 model.has_data=True;model.note='已保存曲线';r['last_record']=model.saved_plot['source']
try:
 r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
 initialized=True
 stop_file.unlink(missing_ok=True)
 model.enabled=[v['enabled'] for v in r['initialized']['outputs']];model.gpio=r['initialized']['gpio']['output']
 try:capture()
 except Exception as error:model.note=str(error)[:36]
 pending=upload().get('touch');last_capture=0
 r['running']=True;checkpoint();last_checkpoint=time.monotonic()
 print('LCD_READY '+str(args.report),flush=True)
 while not args.seconds or time.monotonic()-start<args.seconds:
  if stop_file.exists():r['stop_requested']=True;break
  touch=pending or a.call('lcd').get('touch');pending=None;changed=False
  r['touch_polls']=r.get('touch_polls',0)+1
  if touch:
   action=model.touch(*touch);r['actions'].append(dict(touch=touch,action=action));changed=True;model.note=''
   try:
    if action=='stop':a.call('stop')
    elif action and action.startswith('io'):
     bit=1<<int(action[2:]);a.call('gpio',dict(mask=bit,value=model.gpio))
    elif action in ('power','minus','plus','wave','frequency') and model.page=='TX':
     ch=model.tx
     if model.enabled[ch]:
      if ch!=2 and not args.allow_tx12:
       model.enabled[ch]=False;raise ValueError('TX1/TX2接线尚未确认')
      plan=prepare(ch,model.wave if ch==2 else 'dc','voltage',dict(offset=0 if ch==2 else model.volts[ch],peak=model.volts[ch] if ch==2 else 0,
                   frequency_hz=model.frequency,phase_degrees=0,duty_percent=50),cal,confirmed=True,action='start')
      a.call('output',plan['request'])
      basis=plan['request'].get('sine_amplitude_basis')
      model.note={'scope_verified_grid':'幅度实测参考','scope_checked_unstable_reference':'实测参考 · 稳定性未通过'}.get(basis,'幅度参考估算')
     else:a.call('output',dict(channel=ch,action='stop'))
    elif action in ('single','run'):
     if model.page=='RX' and (action=='single' or model.running):capture();last_capture=time.monotonic()
     elif model.page=='BJT':saved()
    elif model.page=='BJT' and action in ('BJT','polarity','mode','size'):saved()
    elif model.page=='RX' and action in ('points','stride'):
     model.has_data=False;model.rx_trace=None;model.note='参数已设定，点击单次或连续'
   except Exception as error:
    model.running=False;model.note=str(error)[:36];r.setdefault('errors',[]).append(str(error))
   state=a.call('status');model.enabled=[v['enabled'] for v in state['outputs']];model.gpio=state['gpio']['output']
  if model.running and model.page=='RX' and time.monotonic()-last_capture>=2:
   try:capture()
   except Exception as error:model.running=False;model.note=str(error)[:36]
   last_capture=time.monotonic();changed=True
  if changed:pending=upload().get('touch')
  if changed or time.monotonic()-last_checkpoint>=10:
   checkpoint();last_checkpoint=time.monotonic()
  time.sleep(.15)
 r['completed']=True
except BaseException as error:r['error']=repr(error)
finally:
 r['running']=False
 try:
  if initialized:
   a.call('stop');model.enabled=[False]*3;model.gpio=0;model.running=False;model.note='控制已停止';upload()
 except Exception as error:r['stop_error']=repr(error)
 try:r['close']=a.close()
 except Exception as error:r['close_error']=repr(error)
 checkpoint()
 print(json.dumps(r,ensure_ascii=False),flush=True)
if 'error' in r or 'stop_error' in r or 'close_error' in r:raise SystemExit(1)
