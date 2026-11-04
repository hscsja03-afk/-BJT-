"""Load the paired custom-carrier overlay and verify muted initialization."""
import argparse
import fcntl
from pathlib import Path
from zynq_bjt.mio import Mio
from zynq_bjt.runtime import Board
from pynq import Overlay

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bitfile', type=Path, required=True)
    args = parser.parse_args()
    if not args.bitfile.is_file() or not args.bitfile.with_suffix('.hwh').is_file():
        parser.error('Both bit and hwh are required')
    with open('/tmp/zynq_bjt_desktop.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Mio.preflight_from_pynq()
        Overlay(str(args.bitfile), download=False).download()
        board = None
        try:
            board = Board.from_pynq(args.bitfile, program=False)
            print(board.initialize(adc_divider=20, dac_divider=8))
            assert all(not board.output(i).enabled for i in range(3))
        finally:
            if board is not None:
                board.close()

if __name__ == '__main__':
    main()
