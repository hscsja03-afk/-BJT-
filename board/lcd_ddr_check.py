"""Locked candidate load, RGB565/DMA exercise and explicit buffer cleanup."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    base=args.manifest.parent
    manifest=json.loads(args.manifest.read_text())
    for name,digest in manifest['files'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Candidate file hash mismatch: '+name)
    sys.path.insert(0,str(base/'agent.pyz'))
    from pynq import PL,MMIO
    from zynq_bjt.runtime import Board
    from zynq_bjt.mio import Mio
    from zynq_bjt.desktop_session import EXPECTED_IDS
    report=dict(passed=False,boot_modified=False,analog_calibration_qualified=False)
    board=None
    lock=open('/tmp/zynq_bjt_desktop.lock','a')
    previous=None
    programmed=False
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=Path(PL.bitfile_name)
        candidate=base/'bjt.bit'
        allowed=dict(manifest['previous'])
        allowed[str(candidate)]={ext:manifest['files']['bjt.'+ext] for ext in ('bit','hwh')}
        if str(previous) not in allowed:raise RuntimeError('Unexpected currently loaded overlay')
        for ext,digest in allowed[str(previous)].items():
            if hashlib.sha256(previous.with_suffix('.'+ext).read_bytes()).hexdigest()!=digest:
                raise ValueError('Loaded source bundle changed')
        target=Path(manifest['production']) if args.restore else candidate
        for ext,digest in allowed[str(target)].items():
            if hashlib.sha256(target.with_suffix('.'+ext).read_bytes()).hexdigest()!=digest:
                raise ValueError('Target bundle changed')
        Mio.preflight_from_pynq()
        if MMIO(0xf8008000,4096).read(0)&1:
            raise RuntimeError('PS HP0 is in 32-bit mode; expected reviewed 64-bit mode')
        old=Board.from_pynq(previous,program=False)
        old.close()
        board=Board.from_pynq(target,program=previous!=target)
        programmed=previous!=target
        report.update(previous=str(previous),target=str(target))
        for address,expected in EXPECTED_IDS.items():
            if board.core.io.read(address)!=expected:raise ValueError('Peripheral identity mismatch')
        report['identity']=board.initialize()
        report['outputs']=[dict(enabled=board.output(i).enabled) for i in range(3)]
        if any(row['enabled'] for row in report['outputs']):raise RuntimeError('Output not muted')
        if not args.restore:
            import numpy as np
            core=board.core
            if core.io.read(0x0c)&0x0c000000!=0x0c000000:raise ValueError('RGB565 capability missing')
            faults=core.io.read(0xe4)
            frames=[(base/('preview%d.rgb565'%i)).read_bytes() for i in (0,1,2)]
            if any(len(p)!=1228800 for p in frames):raise ValueError('Bad test frame')
            times=[];writes=[];captures=[]
            for i in range(32):
                target=frames[i%len(frames)]
                fb=getattr(core,'_framebuffer',None)
                front=fb.buffers[fb.front].copy() if fb is not None and fb.front is not None else None
                front_index=fb.front if fb is not None else None
                start=time.monotonic()
                update=core.display_update(target,native=True)
                writes.append(update['writes'])
                if i>=16:
                    capture_start=time.monotonic()
                    frame=board.capture(sample_count=4096,sample_stride=1)
                    captures.append(dict(seconds=time.monotonic()-capture_start,points=[len(words) for words in frame.words],
                                         overrange=[sum((word>>16)&1 for word in words) for words in frame.words]))
                while update['remaining']:
                    if time.monotonic()-start>3:raise TimeoutError('Frame flip timeout')
                    time.sleep(.002);update=core.display_update(native=True)
                times.append(time.monotonic()-start)
                if front is not None:
                    if not np.array_equal(fb.buffers[front_index],front):raise RuntimeError('Front buffer modified before flip')
                fb=core._framebuffer
                if fb.buffers[fb.front].astype('<u2').tobytes()!=target:raise RuntimeError('Framebuffer readback mismatch')
            time.sleep(5)
            report['display']=dict(first_frame_s=times[0],flip_median_s=statistics.median(times[2:16]),
                capture_and_flip_median_s=statistics.median(times[16:]),frame_times_s=times,
                patched_pixels=writes,framebuffers=[int(b.physical_address) for b in fb.buffers],
                faults_before=faults,faults_after=core.io.read(0xe4),captures=captures,
                physical_appearance_confirmed=False,simulated_waveform=True)
            if core.io.read(0xe4)!=faults:raise RuntimeError('DDR reader reported underflow or AXI error')
            core.close_display()
            report['dma_stopped']=core.io.read(0xe0)&3==0
            if not report['dma_stopped']:raise RuntimeError('DMA stop not confirmed')
        board.close();board=None
        report.update(passed=True,cleanup_confirmed=True)
    except Exception as error:
        report['error']=repr(error)
        if board is not None:
            try:board.close();board=None
            except Exception as cleanup:report['cleanup_error']=repr(cleanup)
        if programmed and previous is not None:
            try:
                rollback=Board.from_pynq(previous,program=True)
                try:report['rollback_identity']=rollback.initialize()
                finally:rollback.close()
                report['rollback_confirmed']=True
            except Exception as rollback_error:report['rollback_error']=repr(rollback_error)
    finally:
        lock.close()
        (base/('restore.json' if args.restore else 'hardware.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
