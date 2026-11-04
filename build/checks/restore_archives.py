"""Restore the selected distribution/data archives and verify their contents."""
import argparse,hashlib,json,shutil,tempfile,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[2]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--group',action='append',help='Archive id; omit to restore all groups')
    args=parser.parse_args()
    groups=json.loads((ROOT/'build/archive_manifest.json').read_text(encoding='utf-8'))['archives']
    known={a['id'] for a in groups}
    if args.group and set(args.group)-known:parser.error('Unknown archive group')
    for item in groups:
        if args.group and item['id'] not in args.group:continue
        with tempfile.TemporaryDirectory() as temp:
            joined=Path(temp)/'archive.zip'
            with joined.open('wb') as out:
                for part in item['parts']:
                    p=ROOT/part['path']
                    if p.stat().st_size!=part['bytes'] or digest(p)!=part['sha256']:raise ValueError('Archive part mismatch: '+part['path'])
                    with p.open('rb') as f:shutil.copyfileobj(f,out)
            if digest(joined)!=item['zip_sha256']:raise ValueError('ZIP hash mismatch')
            with zipfile.ZipFile(joined) as archive:
                expected={e['path']:e for e in item['members']}
                if len(archive.namelist())!=len(expected) or set(archive.namelist())!=set(expected):raise ValueError('Archive inventory mismatch')
                for name,record in expected.items():
                    rel=PurePosixPath(name)
                    if rel.is_absolute() or '..' in rel.parts or ':' in name or '\\' in name:raise ValueError('Invalid archive path')
                    target=ROOT.joinpath(*rel.parts)
                    if ROOT not in target.resolve().parents:raise ValueError('Path outside repository')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(name) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
                    if target.stat().st_size!=record['bytes'] or digest(target)!=record['sha256']:raise ValueError('Restored file mismatch: '+name)
        print(item['id']+': '+str(item['files'])+' files verified')
if __name__=='__main__':main()
