"""Build an independent Windows folder distribution (no system Python needed)."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--distpath',type=Path,default=ROOT/'build/dist/desktop')
args=parser.parse_args()
distpath=args.distpath.resolve()
if not distpath.is_relative_to((ROOT/'build/dist').resolve()):
    parser.error('Desktop distributions must stay within build/dist')
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.desktop_transport import agent_archive

stage = ROOT/'build/work/desktop_package'
stage.mkdir(parents=True, exist_ok=True)
(stage/'agent.pyz').write_bytes(agent_archive(ROOT/'src/python/zynq_bjt'))
runtime_data = stage/'runtime_data'
if runtime_data.exists():
    if not runtime_data.resolve().is_relative_to((ROOT/'build/work').resolve()):
        raise ValueError('Runtime staging directory must stay within build/work')
    shutil.rmtree(runtime_data)
runtime_manifest = json.loads((ROOT/'data/runtime_manifest.json').read_text(encoding='utf-8'))
for item in runtime_manifest['files']:
    source = ROOT/'data'/item['path']
    if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
        raise ValueError('Runtime data hash mismatch: '+item['path'])
    target = runtime_data/item['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir',
           '--name', 'ZynqBjtDesktop', '--distpath', str(distpath),
           '--workpath', str(stage/'pyinstaller'), '--specpath', str(stage),
           '--paths', str(ROOT/'src/python'), '--add-data', str(runtime_data)+':data',
           '--add-data', str(stage/'agent.pyz')+':.', '--hidden-import', 'paramiko',
           '--hidden-import', 'matplotlib.backends.backend_tkagg',
           '--exclude-module', 'IPython', '--exclude-module', 'PyQt5',
           '--exclude-module', 'PyQt6', '--exclude-module', 'PySide6',
           str(ROOT/'board/run_desktop.pyw')]
subprocess.run(command, check=True)
dest = distpath/'ZynqBjtDesktop'
shutil.copyfile(ROOT/'board/desktop_workbench.md', dest/'readme.md')
shutil.copyfile(ROOT/'board/early_rin_datasheet.md', dest/'early_rin_datasheet.md')
manifest = {str(p.relative_to(dest)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in dest.rglob('*') if p.is_file() and p.name != 'manifest.json'}
(dest/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('DESKTOP_EXE='+str(dest/'ZynqBjtDesktop.exe'))
