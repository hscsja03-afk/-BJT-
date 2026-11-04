"""Run an explicitly supplied maintenance script on the logged-in Linux UART.
Transfer uses bounded lines; no password is echoed or recorded.
"""
import argparse,base64,json,os,shlex,time,zlib
from pathlib import Path
from tx2_scope_zero import serial

ap=argparse.ArgumentParser();ap.add_argument('script',type=Path);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--seconds',type=int,default=60);ap.add_argument('--stream',action='store_true')
a=ap.parse_args();payload=base64.b64encode(zlib.compress(a.script.read_bytes())).decode();chunks=[payload[i:i+768] for i in range(0,len(payload),768)]
program='import base64,zlib;print("MAINT_READY",flush=True);n=int(input());s=zlib.decompress(base64.b64decode("".join(input() for _ in range(n))));exec(compile(s,"maintenance","exec"));print("MAINT_OK",flush=True)'
u=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=5);u.dtr=u.rts=False;u.port='COM7'
r={'script':str(a.script),'complete':False};received=bytearray()
try:
 u.open();u.write(b'stty -echo -onlcr\n');u.flush();time.sleep(.3);u.read(u.in_waiting)
 cmd="sudo -S -p 'MAINT_PASSWORD:' python3 -u -c "+shlex.quote(program)+"; stty echo onlcr; printf '\\nMAINT_END\\n'\n"
 u.write(cmd.encode());u.flush();deadline=time.monotonic()+a.seconds;password=False;sent=False
 while time.monotonic()<deadline:
  b=u.read(u.in_waiting or 1);received.extend(b)
  if b and a.stream:print(b.decode(errors='replace'),end='',flush=True)
  if b'MAINT_PASSWORD:' in received and not password:u.write((os.environ['PYNQ_SSH_PASSWORD']+'\n').encode());u.flush();password=True
  if b'MAINT_READY' in received and not sent:
   for line in [str(len(chunks))]+chunks:u.write((line+'\n').encode());u.flush();time.sleep(.02)
   sent=True
  if b'MAINT_END' in received:break
 r['complete']=b'MAINT_OK' in received
 r['output']=received.decode(errors='replace')
 if not a.stream:print(r['output'])
finally:
 u.close();a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2),encoding='utf-8')
if not r['complete']:raise RuntimeError('Maintenance task did not report completion')
