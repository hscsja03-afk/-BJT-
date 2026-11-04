from pathlib import Path
import subprocess,hashlib,json
for command in [['systemctl','list-unit-files','--no-pager'],['findmnt','/boot'],['cat','/boot/boot.py'],['cat','/etc/rc.local']]:
 p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 lines=p.stdout.splitlines()
 if command[0]=='systemctl':lines=[x for x in lines if any(s in x.lower() for s in ('pynq','jupyter','boot','pl_server','zynq'))]
 print(command, '\n'.join(lines))
for name in ('BOOT.BIN','boot.scr','image.ub'):
 p=Path('/boot')/name;print(name,len(p.read_bytes()),hashlib.sha256(p.read_bytes()).hexdigest())
p=Path('/boot/boot.scr');print('BOOT_SCRIPT',repr(p.read_bytes()[64:]))
