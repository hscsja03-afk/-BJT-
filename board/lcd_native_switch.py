"""Board-side, temporary LCD candidate switch. Boot files are never replaced."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--preview-only',action='store_true')
    args=parser.parse_args();manifest=json.loads(args.manifest.read_text())
    base=args.manifest.parent
    for name,digest in manifest['files'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Candidate file hash mismatch: '+name)
    production=Path(manifest['production'])
    for suffix,digest in manifest['production_hashes'].items():
        if hashlib.sha256(production.with_suffix('.'+suffix).read_bytes()).hexdigest()!=digest:
            raise ValueError('Production overlay changed: '+suffix)
    sys.path.insert(0,str(base/'agent.pyz'))
    from pynq import Overlay
    from zynq_bjt.runtime import Board
    from zynq_bjt.mio import Mio
    from zynq_bjt.desktop_session import EXPECTED_IDS
    lock=open('/tmp/zynq_bjt_desktop.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.preview_only:
        from zynq_bjt.mmio import AddaCore
        overlay=Overlay(str(base/'bjt.bit'),download=False)
        if not overlay.is_loaded():raise RuntimeError('Native candidate is not loaded')
        core=AddaCore(overlay.adda_core_0.mmio)
        result=core.display_update((base/'preview.pixels').read_bytes(),native=True)
        while result['remaining']:result=core.display_update(native=True)
        report=dict(passed=True,preview_only=True,simulated_waveform=True,analog_registers_written=False)
        (base/'preview.json').write_text(json.dumps(report))
        print(json.dumps(report),flush=True)
        return
    source,target=(base/'bjt.bit',production) if args.restore else (production,base/'bjt.bit')
    current=Overlay(str(source),download=False)
    if not current.is_loaded():raise RuntimeError('Expected source overlay is not loaded')
    Mio.preflight_from_pynq()
    candidate=Overlay(str(target),download=False)
    info=candidate.ip_dict.get('adda_core_0',{})
    if info.get('phys_addr')!=0x43c00000 or info.get('addr_range')!=0x10000:
        raise ValueError('Candidate address map mismatch')
    # Stop all outputs and release MIO before replacing the PL.
    old=Board.from_pynq(source,program=False);old.close()
    report=dict(source=str(source),target=str(target),boot_modified=False,passed=False)
    board=None
    try:
        board=Board.from_pynq(target,program=True)
        for address,value in EXPECTED_IDS.items():
            if board.core.io.read(address)!=value:raise ValueError('Peripheral identity mismatch')
        native=bool(board.core.io.read(0x0c)&0x08000000)
        if native==args.restore:raise ValueError('LCD capability mismatch')
        report['identity']=board.initialize()
        report['lcd_native']=native
        if native:
            image=(base/'preview.pixels').read_bytes()
            result=board.core.display_update(image,native=True)
            batches=1
            while result['remaining']:
                result=board.core.display_update(native=True);batches+=1
            report['preview_batches']=batches
        report['outputs']=[dict(code=board.output(i).code,enabled=board.output(i).enabled) for i in range(3)]
        if any(v['enabled'] for v in report['outputs']):raise RuntimeError('Output not muted')
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        try:
            if board is not None:board.close();board=None
            rollback=Board.from_pynq(source,program=True)
            try:report['rollback_identity']=rollback.initialize()
            finally:rollback.close()
            report['rollback_confirmed']=True
        except BaseException as recovery:
            report['rollback_error']=repr(recovery)
        raise
    finally:
        try:
            if board is not None:board.close()
            report['cleanup_confirmed']=True
        finally:
            (base/('restore.json' if args.restore else 'load.json')).write_text(json.dumps(report,indent=2))
            print(json.dumps(report),flush=True)


if __name__=='__main__':main()
