"""Move completed legacy flat runs into profile/type folders, retaining hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.result_paths import group

ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('--manifest',type=Path,required=True)
args=ap.parse_args();root=args.root.resolve(strict=True)
report=(json.loads(args.manifest.read_text(encoding='utf-8')) if args.manifest.exists()
        else dict(root=str(root),moves=[],skipped=[],complete=False))
if Path(report['root']).resolve()!=root:raise ValueError('Manifest belongs to another result root')
def save():args.manifest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def hashes(folder):return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
save()
for source in sorted(root.iterdir()):
    if not source.is_dir() or source.is_symlink():continue
    try:
        if (source/'run.json').exists():
            state=json.loads((source/'run.json').read_text(encoding='utf-8-sig'))
            if state.get('status')=='running':report['skipped'].append(dict(path=str(source),reason='running'));continue
            profile=state.get('profile',state.get('config',{}).get('profile','npn_small'))
            measurement=state.get('measurement','input')
            if measurement=='polarity':measurement='detect'
        elif (source/'frame.json').exists():profile,measurement='instrument','scope'
        elif (source/'reading.json').exists():profile,measurement='instrument','meter'
        else:continue
        destination=root/group(profile,measurement)/source.name
        # Both fully resolved ends must remain inside the explicitly supplied root.
        if not source.resolve().is_relative_to(root) or not destination.resolve().is_relative_to(root):raise ValueError('Outside result root')
        if destination.exists():raise FileExistsError(destination)
        entry=next((item for item in report['moves'] if item['source']==str(source)),None)
        if entry is None:
            entry=dict(source=str(source),destination=str(destination),sha256=hashes(source),moved=False)
            report['moves'].append(entry)
        if hashes(source)!=entry['sha256']:raise ValueError('Source changed since manifest')
        save()
        destination.parent.mkdir(parents=True,exist_ok=True)
        source.rename(destination)
        if hashes(destination)!=entry['sha256']:raise RuntimeError('Post-move hash mismatch')
        entry['moved']=True;save()
    except (KeyError,ValueError,PermissionError) as error:report['skipped'].append(dict(path=str(source),reason=str(error)));save()
report['complete']=all(item['moved'] for item in report['moves']);save()
print(json.dumps(dict(moved=sum(item['moved'] for item in report['moves']),pending=sum(not item['moved'] for item in report['moves']),manifest=str(args.manifest))))
