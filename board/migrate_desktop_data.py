"""Copy legacy desktop data without overwriting differing destination files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def migrate(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and target must be separate directories')
    files = sorted(p for p in source.rglob('*') if p.is_file())
    stamp = time.strftime('%Y%m%d_%H%M%S') + '_' + str(time.time_ns())[-6:]
    result = dict(source=str(source), target=str(target), files=[], source_retained=True)
    for original in files:
        relative = original.relative_to(source)
        destination = target / relative
        expected = digest(original)
        conflict = destination.exists() and digest(destination) != expected
        if conflict:
            destination = target/'migration_conflicts'/stamp/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(original, destination)
        if digest(destination) != expected or digest(original) != expected:
            raise RuntimeError('File changed during migration: '+str(relative))
        result['files'].append(dict(source=str(relative), destination=str(destination.relative_to(target)),
                                    sha256=expected, conflict_preserved=conflict))
    result['verified'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = migrate(args.source, args.target)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(verified=result['verified'], files=len(result['files']), target=result['target'])))
