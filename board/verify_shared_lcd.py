"""Verify desktop + LCD through one SSH connection; keep TX muted throughout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import tkinter as tk

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt import desktop


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--bitfile',help='Attach to an already-loaded candidate')
    parser.add_argument('--expect-native',action='store_true')
    args=parser.parse_args();args.report.parent.mkdir(parents=True,exist_ok=True)
    desktop.assets=lambda:args.base.resolve()
    workspace=args.report.parent/'hardware_workspace';workspace.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'measurements/known_hosts',workspace/'known_hosts')
    root=tk.Tk();root.withdraw();app=desktop.App(root,workspace=workspace)
    app.board_bitfile=args.bitfile
    report=dict(passed=False,errors=[],calls=[],max_parallel_calls=0)
    frame_times=[]
    render_capture=app.render_capture
    def receive_frame(frame):
        render_capture(frame)
        frame_times.append(time.monotonic())
    app.render_capture=receive_frame
    def sample_window(seconds):
        import statistics
        start=time.monotonic();first=len(frame_times);end=start+seconds
        while time.monotonic()<end:root.update();time.sleep(.005)
        values=frame_times[first:];gaps=[b-a for a,b in zip(values,values[1:])]
        return dict(frames=len(values),seconds=time.monotonic()-start,
                    median_gap_s=statistics.median(gaps) if gaps else None,max_gap_s=max(gaps,default=0))
    app.error=lambda value:report['errors'].append(str(value))
    def wait(predicate,seconds=60):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            root.update()
            if report['errors']:raise RuntimeError(report['errors'][-1])
            if predicate():return
            time.sleep(.02)
        raise TimeoutError('Desktop condition timed out')
    try:
        app.password.set(os.environ['PYNQ_SSH_PASSWORD']);app.connect()
        wait(lambda:app.transport is not None and not app.busy)
        report['connected']=app.last_status
        original=app.transport.inner.call;active=[0];guard=threading.Lock()
        def recorded(op,*values,**kwargs):
            with guard:
                active[0]+=1;report['max_parallel_calls']=max(report['max_parallel_calls'],active[0])
            start=time.monotonic()
            result=None
            try:
                result=original(op,*values,**kwargs)
                return result
            finally:
                with guard:
                    active[0]-=1
                    call=dict(op=op,seconds=time.monotonic()-start)
                    if op=='lcd' and isinstance(result,dict):call.update(writes=result.get('writes'),remaining=result.get('remaining'))
                    report['calls'].append(call)
                    with args.report.with_suffix('.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(call)+'\n')
        app.transport.inner.call=recorded
        app.submit('initialize');wait(lambda:not app.busy,120)
        report['initialized']=app.last_status
        if args.expect_native:assert app.last_status.get('lcd_native'), 'Native LCD capability missing'
        assert not any(v['enabled'] for v in app.last_status['outputs'])
        if args.benchmark:app.lcd.enabled.set(False);app.lcd.changed()
        app.show_page('scope');app.scope.mode.set('Auto');app.scope.sample_count.set('4096')
        app.scope.sample_stride.set('13' if args.benchmark else '1');app.scope.run()
        if args.benchmark:
            wait(lambda:app.last_frame is not None)
            report['baseline_lcd_off']=sample_window(5)
            app.lcd.enabled.set(True);app.lcd.changed();initial=time.monotonic()
        wait(lambda:app.last_frame is not None and app.lcd.last_hash is not None)
        if args.benchmark:report['first_lcd_frame_s']=time.monotonic()-initial
        first=app.last_frame['sequence'];deadline=time.monotonic()+8
        before_frames=app.lcd.frames_completed
        report['lcd_on']=sample_window(8)
        report['lcd_on']['lcd_frames_completed']=app.lcd.frames_completed-before_frames
        assert app.scope.accepting
        assert app.last_frame['sequence']!=first
        assert not app.lcd.failed
        report['frame']=dict(sequence=app.last_frame['sequence'],points=len(app.last_frame['words'][0]),
                            simulated=app.last_frame['simulated'],sample_rates_hz=app.last_frame['sample_rates_hz'])
        report['lcd_status']=app.lcd.status.get()
        report['lcd_native']=app.lcd.model.native
        report['lcd_frame_state']=dict(page=app.lcd.model.page,has_data=app.lcd.model.has_data,
                                      note=app.lcd.model.note,trace_points=[len(c) for c in app.lcd.model.rx_trace or []],
                                      overrange=[c['overrange'] for c in app.scope.converted])
        args.report.with_name('captured_frame.json').write_text(json.dumps(app.last_frame),encoding='utf8')
        if args.expect_native:assert app.lcd.model.render().size==(1024,600)
        app.scope.stop();wait(lambda:not app.busy)
        app.lcd.model.render().resize((1024,600),resample=0).save(args.report.parent/'shared_rx_frame.png')
        app.submit('stop');wait(lambda:not app.busy)
        report['final_status']=app.last_status
        assert not any(v['enabled'] for v in app.last_status['outputs'])
        if args.expect_native:
            import base64,zlib
            app.lcd.enabled.set(False);app.lcd.changed()
            wait(lambda:not app.lcd.inflight)
            app.lcd.model.running=False
            app.lcd.sync()
            app.lcd.model.note=('原生 1024×600 · 显示预览（已暂停）' if app.lcd.model.has_data else
                                app.lcd.model.note+' · 已暂停')
            preview=app.lcd.model.render()
            request=dict(native=True,incremental=True,max_writes=8192,
                         pixels=base64.b64encode(zlib.compress(preview.tobytes(),1)).decode())
            value=app.transport.call('lcd',request)
            while value['remaining']:
                value=app.transport.call('lcd',dict(native=True,incremental=True,max_writes=8192))
            preview.save(args.report.parent/'shared_rx_frame.png')
            report['frozen_preview_uploaded']=True
        assert report['max_parallel_calls']==1
        assert sum(c['op']=='lcd' for c in report['calls'])>=3
        # Read back the exact content-addressed agent deployed by this connection.
        inner=app.transport.inner;archive=(args.base/'agent.pyz').read_bytes()
        data={p.name:p.read_bytes() for p in (args.base/'data').glob('*.json')}
        digest=hashlib.sha256(archive+b''.join(data[n] for n in sorted(data))).hexdigest()[:20]
        with inner.client.open_sftp() as sftp:
            remote=inner.remote_root+'/'+digest
            checks={}
            for name,value in dict({'agent.pyz':archive},**{'data/'+k:v for k,v in data.items()}).items():
                with sftp.open(remote+'/'+name,'rb') as stream:observed=stream.read()
                assert hashlib.sha256(observed).digest()==hashlib.sha256(value).digest(),name
                checks[name]=hashlib.sha256(observed).hexdigest()
        report['deployed']=dict(remote=remote,hashes=checks)
        app.disconnect();wait(lambda:app.transport is None and not app.busy)
        assert '清理已确认' in app.status_var.get()
        report['cleanup_confirmed']=True;report['passed']=True
    except Exception as error:report['error']=repr(error)
    finally:
        if app.transport:
            try:
                app.scope.stop();wait(lambda:not app.busy,30)
                report['cleanup']=app.transport.close()
            except Exception as error:report['cleanup_error']=repr(error)
        app.lcd.close()
        for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
        root.destroy()
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ('passed','error','cleanup_confirmed') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
