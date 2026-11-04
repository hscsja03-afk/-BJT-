import subprocess
subprocess.run(['sync'],check=True)
subprocess.Popen(['/bin/bash','-c','sleep 2; /sbin/poweroff'],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('Orderly poweroff scheduled for QSPI maintenance')
