"""Validate muted ADDA initialization and raw capture over the user's UART.

Never enables outputs or writes persistent storage. Preserve failures and raw
serial bytes; all commands use the normal firmware CRC protocol.
"""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))
sys.path.insert(0,str(ROOT/'build/tool_deps/serial_runtime'))
from zynq_bjt.baremetal import BaremetalBoard


class Trace:
    def __init__(self,stream,tx,rx):self.stream,self.tx,self.rx=stream,tx,rx
    def write(self,data):
        self.tx.write(data);self.tx.flush();return self.stream.write(data)
    def read(self,count):
        data=self.stream.read(count)
        if data:self.rx.write(data)
        return data
    def close(self):self.stream.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--frames',type=int,default=3,choices=range(1,11))
    parser.add_argument('--input-condition',default='unspecified',
                        help='User-reported wiring/source setting; not an independently measured voltage')
    args=parser.parse_args()
    prefix=ROOT/'build/logs'/('baremetal_uart_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    result={'port':args.port,'baud':115200,'format':'8N1','dtr':False,'rts':False,
            'outputs_requested_enabled':False,'storage_written':False,'complete':False,
            'phase':'open','frames':[],'cleanup_error':None,
            'input_condition_user_report':args.input_condition}
    board=None
    with prefix.with_suffix('.tx.bin').open('xb') as tx,prefix.with_suffix('.rx.bin').open('xb') as rx:
        try:
            board=BaremetalBoard.open(args.port,ROOT/'build/work/baseline50')
            board.link.serial=Trace(board.link.serial,tx,rx)
            result['identity']=dict(board.identity)
            result['ping']=board.link.command(1)
            result['phase']='initialize_muted'
            result['initialization']=board.initialize()
            result['phase']='output_readback'
            result['outputs_before']=[asdict(board.output(ch)) for ch in range(3)]
            if any(s['enabled'] for s in result['outputs_before']):raise RuntimeError('Output unexpectedly enabled')
            result['gpio_before']=board.gpio()
            result['phase']='raw_capture'
            for i in range(args.frames):
                frame=board.capture()
                result['frames'].append(asdict(frame))
                print('RAW_FRAME',i,'sequence',frame.sequence,'range',
                      [(min(frame.codes(ch)),max(frame.codes(ch)),frame.overrange(ch)) for ch in range(2)],flush=True)
            result['outputs_after']=[asdict(board.output(ch)) for ch in range(3)]
            if any(s['enabled'] for s in result['outputs_after']):raise RuntimeError('Output enabled during capture')
            result['complete']=True;result['phase']='complete_muted_capture'
        except BaseException as error:
            result['error']=f'{type(error).__name__}: {error}'
            traceback.print_exc()
        finally:
            if board is not None:
                try:board.close()
                except Exception as error:result['cleanup_error']=f'{type(error).__name__}: {error}'
            rx.flush()
    for direction in ('tx','rx'):
        p=prefix.with_suffix(f'.{direction}.bin')
        result[direction+'_evidence']={'path':p.relative_to(ROOT).as_posix(),
            'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
    result['limits']='Raw ADC codes with outputs muted; not analog calibration, output accuracy or full competition validation. Trace starts after initial open/identity check.'
    target=prefix.with_suffix('.json')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('UART_RESULT',target,'complete',result['complete'],'phase',result['phase'],'cleanup',result['cleanup_error'])
    if not result['complete'] or result['cleanup_error']:raise SystemExit(1)


if __name__=='__main__':main()
