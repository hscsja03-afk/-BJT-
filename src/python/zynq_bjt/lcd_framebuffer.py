"""Owned RGB565 DDR buffers; flip at vertical blank, patch only the back buffer."""
import time


class Framebuffer:
    def __init__(self, io, allocate=None):
        import numpy as np
        if allocate is None:
            from pynq import allocate
        self.io=io
        self.buffers=[]
        self.shadows=[np.zeros((600,1024),dtype=np.uint16) for _ in range(2)]
        self.front=None
        self.pending=None
        self.queued=None
        try:
            for _ in range(2):
                buffer=allocate(shape=(600,1024),dtype=np.uint16)
                self.buffers.append(buffer)
                address=int(buffer.physical_address)
                if address&4095 or not 0<address<0x40000000-1228800:
                    raise ValueError('LCD buffer must be page-aligned within PS DDR')
                buffer[:]=0
                buffer.flush()
        except Exception:
            for buffer in self.buffers:buffer.freebuffer()
            raise

    def update(self,pixels=None):
        import numpy as np
        if pixels is not None:
            if not isinstance(pixels,bytes) or len(pixels)!=1228800:
                raise ValueError('Expected native RGB565 little-endian frame')
            self.queued=pixels
        if self.pending is not None:
            index,started=self.pending
            if self.io.read(0xe0)&0x3fffffc1!=int(self.buffers[index].physical_address)|1:
                if time.monotonic()-started>1:
                    raise TimeoutError('LCD frame flip not acknowledged; buffers retained')
                return dict(writes=0,remaining=1)
            self.front=index
            self.pending=None
        pixels,self.queued=self.queued,None
        if pixels is None:return dict(writes=0,remaining=0)
        target=np.frombuffer(pixels,dtype='<u2').reshape(600,1024)
        if self.front is not None and np.array_equal(self.shadows[self.front],target):
            return dict(writes=0,remaining=0)
        index=0 if self.front is None else 1-self.front
        back=self.buffers[index]
        changed=self.shadows[index]!=target
        count=0
        if np.count_nonzero(changed)>target.size//2:
            back[:]=target
            count=int(target.size)
        else:
            for row in np.flatnonzero(changed.any(axis=1)):
                columns=np.flatnonzero(changed[row])
                first,last=int(columns[0]),int(columns[-1])+1
                back[row,first:last]=target[row,first:last]
                count+=last-first
        back.flush()
        self.shadows[index][:]=target
        self.io.write(0x6c,0x40000000|int(back.physical_address))
        self.io.write(0x6c,0xc0000005)
        self.pending=(index,time.monotonic())
        return dict(writes=count,remaining=1)

    def close(self):
        # Do not free memory until the reader has stopped and drained its AXI burst.
        self.io.write(0x6c,0xc0000004)
        # A not-yet-latched enable can still have status=0. Allow a complete
        # 17.1 ms scan period after the ordered disable write before trusting idle.
        time.sleep(.025)
        deadline=time.monotonic()+1
        while self.io.read(0xe0)&3:
            if time.monotonic()>=deadline:
                raise TimeoutError('LCD DMA stop not acknowledged; buffers retained')
            time.sleep(.005)
        for buffer in self.buffers:buffer.freebuffer()
        self.buffers=[];self.shadows=[];self.pending=None;self.front=None;self.queued=None
