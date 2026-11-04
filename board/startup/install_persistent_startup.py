"""Run through uart_root_task; back up files before installing eMMC autostart."""
from pathlib import Path
import subprocess,hashlib,shutil,json,struct,zlib,time
backup=Path('/home/xilinx/persistence_backup_20261030');backup.mkdir(exist_ok=True)
for name in ('boot.scr','boot.py','BOOT.BIN'):
 src=Path('/boot')/name;dest=backup/name
 if not dest.exists():shutil.copyfile(src,dest)
print('BOOT_BACKUP',json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir() if p.is_file()}))
script=b'''echo ZYNQ_BJT_EMMC_BOOT_V1
setenv bootargs console=ttyPS0,115200 root=PARTUUID=d347d9ef-02 rw rootfstype=ext4 rootwait devtmpfs.mount=1 uio_pdrv_genirq.of_id=generic-uio clk_ignore_unused
if mmc dev 0; then
 if fatload mmc 0:1 0x10000000 image.ub; then
  if iminfo 0x10000000; then
   bootm 0x10000000
  fi
 fi
fi
echo ZYNQ_BJT_EMMC_BOOT_FAILED
'''
payload=struct.pack('>II',len(script),0)+script
header=struct.pack('>7I4B32s',0x27051956,0,int(time.time()),len(payload),0,0,zlib.crc32(payload)&0xffffffff,5,2,6,0,b'Zynq BJT eMMC boot')
header=header[:4]+struct.pack('>I',zlib.crc32(header)&0xffffffff)+header[8:]
(Path('/boot')/'boot.scr').write_bytes(header+payload)
startup='''from pathlib import Path
import sys,hashlib,json,fcntl
agent=Path('/home/xilinx/.zynq_bjt_desktop/1fec68fce6f25b9007bb/agent.pyz')
agent_sha256=hashlib.sha256(agent.read_bytes()).hexdigest()
assert agent_sha256=='0c332428861cb7a16754a3f4aa8b4cf09f895e256aa8dd1c2a637d329b68582c'
sys.path.insert(0,str(agent))
from pynq import Overlay
from zynq_bjt.mio import Mio
from zynq_bjt.runtime import Board
bit=Path('/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit')
assert hashlib.sha256(bit.read_bytes()).hexdigest()=='7c38abf4caec30d28f239a0eac8ed336e917c78d89245af82ff43e214ba2e8af'
assert hashlib.sha256(bit.with_suffix('.hwh').read_bytes()).hexdigest()=='ce553040ea915752e440d0eab0406b1e947076f19586ef5c4ea957d3596db600'
lock=open('/tmp/zynq_bjt_desktop.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
Mio.preflight_from_pynq()
Overlay(str(bit),download=False).download()
board=None
try:
 board=Board.from_pynq(bit,program=False)
 identity=board.initialize(adc_divider=20,dac_divider=20)
 assert all(not board.output(i).enabled for i in range(3))
finally:
 if board is not None:board.close()
result={'ready':True,'outputs_enabled':False,'identity':identity,'agent':str(agent),'agent_sha256':agent_sha256}
Path('/run/zynq_bjt_ready.json').write_text(json.dumps(result,indent=2))
print('ZYNQ_BJT_AUTOSTART_READY',json.dumps(result),flush=True)
'''
dest=Path('/usr/local/lib/zynq_bjt_autostart.py');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(startup)
unit='''[Unit]
Description=Custom ADDA overlay and muted startup verification
After=pl_server.service bootpy.service
Requires=pl_server.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u /usr/local/lib/zynq_bjt_autostart.py'
RemainAfterExit=yes
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
'''
Path('/etc/systemd/system/zynq-bjt-startup.service').write_text(unit)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','zynq-bjt-startup.service'],check=True)
subprocess.run(['systemctl','start','zynq-bjt-startup.service'],check=True)
print(Path('/run/zynq_bjt_ready.json').read_text())
subprocess.run(['sync'],check=True)
print('STARTUP_INSTALLED',hashlib.sha256(Path('/boot/boot.scr').read_bytes()).hexdigest())
