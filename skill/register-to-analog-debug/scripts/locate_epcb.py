"""Read placements from an EPRO or a ZIP containing EPRO; no extraction or board access."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile


def choose(names, suffix, requested=None):
    matches = [n for n in names if n.lower().endswith(suffix)]
    if requested is not None:
        if requested not in matches:
            raise ValueError('Requested member not found: ' + requested)
        return requested
    if len(matches) != 1:
        raise ValueError(f'Expected one {suffix} member, found {len(matches)}; select explicitly')
    return matches[0]


def locate(source, refs, epro_member=None, pcb_member=None):
    raw = Path(source).read_bytes()
    archive = ZipFile(io.BytesIO(raw))
    member = None
    if not any(n.lower().endswith('.epcb') for n in archive.namelist()):
        member = choose(archive.namelist(), '.epro', epro_member)
        archive = ZipFile(io.BytesIO(archive.read(member)))
    elif epro_member is not None:
        raise ValueError('--epro-member applies only to an outer ZIP')
    pcb = choose(archive.namelist(), '.epcb', pcb_member)
    content = archive.read(pcb)
    records = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
    designators = {}
    for r in records:
        if r[0] == 'ATTR' and len(r) > 8 and r[7] == 'Designator':
            designators[r[3]] = r[8]
    found = {}
    for r in records:
        if r[0] == 'COMPONENT' and len(r) > 6 and designators.get(r[1]) in refs:
            ref = designators[r[1]]
            if ref in found:
                raise ValueError('Duplicate designator: ' + ref)
            if not all(isinstance(v, (int, float)) for v in r[4:7]):
                raise ValueError('Unsupported placement format')
            found[ref] = dict(layer_code=r[3], x=r[4], y=r[5], rotation=r[6])
    missing = sorted(set(refs) - set(found))
    if missing:
        raise ValueError('Missing designators: ' + ', '.join(missing))
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(), epro_member=member,
                pcb_member=pcb, pcb_sha256=hashlib.sha256(content).hexdigest(), placements=found,
                units='source-native, not photo pixels', model_verified=False,
                photo_position_verified=False, hardware_validated=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--ref', action='append', required=True)
    p.add_argument('--epro-member')
    p.add_argument('--pcb-member')
    a = p.parse_args()
    try:
        print(json.dumps(locate(a.source, a.ref, a.epro_member, a.pcb_member), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as e:
        p.exit(1, str(e) + '\n')
