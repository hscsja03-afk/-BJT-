"""Check packaged files without importing board libraries or accessing hardware."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    entries = manifest['files']
    seen = set()
    for entry in entries:
        name = entry['path']
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name or name in seen:
            raise ValueError('Unsafe or duplicate manifest entry: ' + name)
        if any(re.fullmatch(r'[a-z0-9_.-]+', part) is None for part in rel.parts):
            raise ValueError('Use lowercase ASCII file and directory names: ' + name)
        seen.add(name)
        path = ROOT.joinpath(*rel.parts)
        if not path.is_file():
            raise FileNotFoundError(name)
        if path.stat().st_size != entry['bytes']:
            raise ValueError('Size mismatch: ' + name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry['sha256']:
            raise ValueError('SHA256 mismatch: ' + name)
    print(json.dumps({'files': len(entries), 'integrity': 'passed'}, indent=2))


if __name__ == '__main__':
    main()
