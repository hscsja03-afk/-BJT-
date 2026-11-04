"""PYNQ-independent register driver with explicit timeouts and injected MMIO.

No constructor programs the FPGA or initializes analog outputs. The caller owns
the selected overlay and supplies its verified adda_core_0.mmio object.
"""
from dataclasses import dataclass, fields
import threading
import time
import math


@dataclass(frozen=True)
class Frame:
    sequence: int
    words: tuple
    sample_rates_hz: tuple
    captured_at: float
    simulated: bool = False
    starts_aligned: bool = False
    adc_sample_rates_hz: tuple = ()
    sample_stride: int = 1
    captured_channels: tuple = (0, 1)

    def __post_init__(self):
        validate_capture_channels(self.captured_channels)
        count = len(self.words[self.captured_channels[0]]) if len(self.words)==2 else 0
        if not 8 <= count <= 4096 or len(self.words) != 2 or any(len(w) != (count if ch in self.captured_channels else 0)
                                      for ch, w in enumerate(self.words)):
            raise ValueError("Expected complete snapshots for selected channels only")
        if any(type(v) is not int or not 0 <= v <= 0x1ffff for ch in self.words for v in ch):
            raise ValueError("Invalid ADC snapshot word")
        if len(self.sample_rates_hz) != 2 or any(v <= 0 for v in self.sample_rates_hz):
            raise ValueError("Invalid ADC sample rates")

    def codes(self, channel):
        if channel not in self.captured_channels: raise ValueError('ADC channel was not read')
        return tuple(v & 65535 for v in self.words[channel])

    def overrange(self, channel):
        if channel not in self.captured_channels: raise ValueError('ADC channel was not read')
        return sum(v >> 16 for v in self.words[channel])

    def as_record(self):
        """Serialize immutable samples without deep-copying 2048 integers.

        JSON encoding is synchronous; the tuple samples and scalar metadata
        retain exactly the historical dataclass record layout.
        """
        return {field.name:getattr(self,field.name) for field in fields(self)}


def validate_capture_channels(channels):
    if (not isinstance(channels, (tuple, list)) or not 1 <= len(channels) <= 2
            or any(type(ch) is not int or ch not in (0, 1) for ch in channels)
            or len(set(channels)) != len(channels)):
        raise ValueError('Select RX1, RX2, or both ADC channels')


class AddaCore:
    def __init__(self, mmio, *, clock=time.monotonic, pause=time.sleep):
        self.io, self.clock, self.pause = mmio, clock, pause
        self.lock = threading.RLock()
        self.sequence = 0
        expected = {0: 0x41444441, 0x20: 1024, 0x44: 0x54583101,
                    0x48: 0x47504901, 0x80: 0x41574701}
        for address, value in expected.items():
            if mmio.read(address) != value:
                raise ValueError(f"Unexpected peripheral identity at 0x{address:04x}")

    def wait(self, predicate, timeout=.5):
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        end = self.clock() + timeout
        while not predicate():
            if self.clock() >= end:
                raise TimeoutError("Peripheral handshake did not complete")
            self.pause(.001)

    def gpio(self, mask=None, value=None):
        with self.lock:
            before = self.io.read(0x4c)
            if mask is not None:
                if type(mask) is not int or type(value) is not int or not 0 <= mask <= 127 or not 0 <= value <= 127:
                    raise ValueError("GPIO mask/value must be seven-bit integers")
                self.io.write(0x50, (mask << 8) | value)
                self.wait(lambda: (self.io.read(0x4c) & mask) == (value & mask))
            current = self.io.read(0x4c)
            output, sense = current & 127, (current >> 8) & 127
            if mask is not None and ((output ^ (before & 127)) & (~mask & 127)):
                raise RuntimeError("Unowned GPIO changed during transaction")
            if mask is not None and (output ^ sense) & mask:
                raise RuntimeError("GPIO output/sense mismatch; contact state not established")
            return {"output": output, "sense": sense, "sequence": self.io.read(0x54)}

    def capture(self, sample_rates_hz, timeout=.5, sample_stride=1, channels=(0, 1), sample_count=1024):
        validate_capture_channels(channels)
        if type(sample_stride) is not int or not 1 <= sample_stride <= 256:
            raise ValueError('Snapshot stride must be 1..256')
        if type(sample_count) is not int or not 8 <= sample_count <= 4096:
            raise ValueError('Snapshot count must be 8..4096')
        with self.lock:
            if self.io.read(0x0c) & 8:
                raise RuntimeError("Previous capture still busy")
            # Never probe an unmapped register: old AXI slaves return SLVERR,
            # which can terminate a PYNQ process with SIGBUS.
            extended = bool(self.io.read(0x0c) & 0x80000000)
            long_capture = bool(self.io.read(0x0c) & 0x20000000)
            if long_capture:
                if self.io.read(0xcc) != 4096: raise RuntimeError('Unexpected capture depth')
                self.io.write(0xd0, sample_count)
                if self.io.read(0xd0)!=sample_count: raise RuntimeError('Capture count readback mismatch')
            elif sample_count>1024:
                raise RuntimeError('当前位流最多1024点，请加载4096点位流')
            if extended and self.io.read(0xc4) != 0x53435001:
                raise RuntimeError('Unexpected extended capture identity')
            if sample_stride != 1 and not extended:
                raise RuntimeError('长窗口需要配套示波器位流；请更新位流或选择 20 µs 短窗口')
            if extended:
                self.io.write(0xc8, sample_stride)
                if self.io.read(0xc8) != sample_stride:
                    raise RuntimeError('Snapshot stride readback mismatch')
            # AXI write response occurs after toggling the request; old DONE bits
            # cannot be accepted until the write has completed.
            self.io.write(8, 1)
            self.wait(lambda: self.io.read(0x0c) & 0xb == 3, timeout)
            # Physical RAM A is RX2; RAM B is RX1. Keep UI ordering explicit.
            # The current bitstream has a shared trigger. Only read the selected
            # RAMs; an omitted channel is empty, never padded with invented data.
            bases = (0x8000,0x4000) if long_capture else (0x2000,0x1000)
            device=getattr(self.io,'device',None)
            mapped=device is not None and device.has_capability('MEMORY_MAPPED')
            def read_snapshot(base):
                if mapped:
                    # Snapshot RAM has no read side effects. Own the returned
                    # copy before releasing the lock or arming the next frame.
                    return tuple(self.io.array[base//4:base//4+sample_count].copy().tolist())
                return tuple(int(self.io.read(base+4*i)) for i in range(sample_count))
            words=tuple(read_snapshot(base) if ch in channels else () for ch,base in enumerate(bases))
            self.sequence += 1
            return Frame(self.sequence, words, tuple(r/sample_stride for r in sample_rates_hz), time.time(),
                         adc_sample_rates_hz=tuple(sample_rates_hz), sample_stride=sample_stride,
                         captured_channels=tuple(channels))

    def capture_statistics(self, sample_count, timeout=2.0):
        """Capture simultaneous per-channel mean/RMS statistics in the ADC clock domains."""
        if type(sample_count) is not int or not 8 <= sample_count <= 50000:
            raise ValueError("Statistics window must contain 8..50000 samples")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Statistics timeout must be positive")
        with self.lock:
            if self.io.read(0x0c) & 8:
                raise RuntimeError("Raw ADC capture is still busy")
            if self.io.read(0xa0) & 1:
                raise RuntimeError("ADC statistics capture is still busy")
            self.io.write(0x9c, sample_count)
            self.io.write(0xa0, 1)
            deadline = self.clock() + timeout
            saw_busy = False
            while self.clock() < deadline:
                status = self.io.read(0xa0)
                saw_busy = saw_busy or bool(status & 1)
                if saw_busy and not (status & 1) and (status & 8):
                    break
                self.pause(.001)
            else:
                raise TimeoutError("ADC statistics handshake did not complete")

            channels = []
            for sum_address, square_low_address, square_high_address, fault_address in (
                    (0xa4, 0xa8, 0xac, 0xbc), (0xb0, 0xb4, 0xb8, 0xc0)):
                sum_word = self.io.read(sum_address)
                sum_centered = sum_word if sum_word < 0x80000000 else sum_word - 0x100000000
                sumsq = self.io.read(square_low_address) | ((self.io.read(square_high_address) & 0xffff) << 32)
                mean_centered = sum_centered / sample_count
                variance = max(0.0, sumsq / sample_count - mean_centered * mean_centered)
                channels.append({"mean_code": 32768.0 + mean_centered,
                                 "rms_code": math.sqrt(variance),
                                 "fault_count": self.io.read(fault_address)})
            return {"sample_count": sample_count, "channels": channels,
                    "completed_at": time.time()}

    def clock_rates(self, interval=.25):
        if not .02 <= interval <= 1:
            raise ValueError("Clock measurement interval outside .02..1 seconds")
        with self.lock:
            def snapshot():
                values=[]
                for address in (0x24,0x28,0x2c):
                    start=self.clock();value=self.io.read(address);end=self.clock()
                    values.append((value,(start+end)/2))
                return values
            before = snapshot()
            self.pause(interval)
            after = snapshot()
            return tuple(((b[0]-a[0]) & 0xffffffff)/(b[1]-a[1]) for a,b in zip(before,after))

    def display_image(self, image):
        """新版LCD图层；旧位流在任何写操作前拒绝。"""
        from .lcd import image_words
        words = image_words(image)
        with self.lock:
            self._invalidate_lcd_update()
            if not self.io.read(0x0c) & 0x40000000:
                raise RuntimeError('LCD graphics requires the updated bitstream')
            if image.size==(1024,600) and not self.io.read(0x0c)&0x08000000:
                raise RuntimeError('Native LCD requires the 1024x600 bitstream')
            self.io.write(0x68, 1)
            for word in words:
                self.io.write(0x6c, word)

    def display_touch(self):
        """返回一次触摸坐标，无事件时返回None。"""
        with self.lock:
            event = self.io.read(0x60)
            if not event & 0x80000000:
                return None
            self.io.write(0x64, 1)
            return event & 2047, (event >> 11) & 2047

    def display_pixels(self, pixels):
        """上传旧版或原生索引像素，不依赖板端图形库。"""
        if not isinstance(pixels, bytes) or len(pixels) not in (512*300,1024*600) or max(pixels)>15:
            raise ValueError('Invalid LCD indexed pixels')
        native=len(pixels)==1024*600
        command,shift,mode=(0xa0000000,19,2) if native else (0x80000000,17,0)
        with self.lock:
            self._invalidate_lcd_update()
            if not self.io.read(0x0c)&0x40000000:
                raise RuntimeError('LCD graphics requires the updated bitstream')
            if native and not self.io.read(0x0c)&0x08000000:
                raise RuntimeError('Native LCD requires the 1024x600 bitstream')
            self.io.write(0x68,1);self.io.write(0x6c,0xc0000000|mode)
            for i in range(0,len(pixels),2):
                self.io.write(0x6c,command | i//2 | ((pixels[i] | pixels[i+1]<<4)<<shift))
            self.io.write(0x6c,0xc0000001|mode)

    def _invalidate_lcd_update(self):
        self._lcd_pairs=None
        self._lcd_pending=None
        self._lcd_native=None

    def display_update(self, pixels=None, max_writes=8192, native=False):
        """Diff framebuffer pairs and write one bounded batch without blanking.

        Other commands may run between batches. Cache entries are committed only
        after the corresponding MMIO write; a replacement frame uses that cache.
        """
        if type(max_writes) is not int or not 1<=max_writes<=8192:
            raise ValueError('Invalid LCD update budget')
        if type(native) is not bool:raise ValueError('Invalid LCD resolution')
        if self.io.read(0x0c)&0x04000000:
            if not native:raise ValueError('DDR LCD requires native resolution')
            if pixels is not None and (not isinstance(pixels,bytes) or len(pixels) not in (614400,1228800)):
                raise ValueError('Invalid native LCD pixels')
            with self.lock:
                if pixels is not None and len(pixels)==1024*600:
                    from .lcd import PALETTE
                    import numpy as np
                    if max(pixels)>15:raise ValueError('Invalid LCD palette')
                    colors=np.array([int(c,16) for c in PALETTE],dtype=np.uint32)
                    lut=(((colors>>19)<<11)|(((colors>>10)&63)<<5)|((colors>>3)&31)).astype('<u2')
                    pixels=lut[np.frombuffer(pixels,dtype=np.uint8)].tobytes()
                if getattr(self,'_framebuffer',None) is None:
                    if pixels is None:return dict(writes=0,remaining=0)
                    from .lcd_framebuffer import Framebuffer
                    self._framebuffer=Framebuffer(self.io)
                return self._framebuffer.update(pixels)
        count=1024*600 if native else 512*300
        command,shift,mode=(0xa0000000,19,2) if native else (0x80000000,17,0)
        if pixels is not None and (not isinstance(pixels,bytes) or len(pixels)!=count or max(pixels)>15):
            raise ValueError('Invalid LCD indexed pixels')
        import numpy as np
        with self.lock:
            if not self.io.read(0x0c)&0x40000000:
                raise RuntimeError('LCD graphics requires the updated bitstream')
            if native and not self.io.read(0x0c)&0x08000000:
                raise RuntimeError('Native LCD requires the 1024x600 bitstream')
            previous=getattr(self,'_lcd_native',None)
            if pixels is None and previous is not None and native!=previous:
                raise ValueError('LCD resolution change requires a complete frame')
            if pixels is not None:
                values=np.frombuffer(pixels,dtype=np.uint8)
                target=values[::2] | (values[1::2]<<4)
                if getattr(self,'_lcd_pairs',None) is None or previous!=native:
                    # Hide only a resolution transition, never a steady-frame patch.
                    if native or previous is True:self.io.write(0x6c,0xc0000000|mode)
                    self._lcd_pairs=np.full(count//2,-1,dtype=np.int16)
                    self._lcd_native=native
                indices=np.flatnonzero(target!=self._lcd_pairs).astype(np.uint32)
                self._lcd_pending=(indices,target,0)
            pending=getattr(self,'_lcd_pending',None)
            if pending is None:return dict(writes=0,remaining=0)
            indices,target,start=pending
            stop=min(start+max_writes,len(indices))
            addresses=indices[start:stop]
            words=np.uint32(command) | addresses | (target[addresses].astype(np.uint32)<<shift)
            device=getattr(self.io,'device',None)
            mapped=device is not None and device.has_capability('MEMORY_MAPPED')
            # This is the same ndarray store used by PYNQ MMIO.write_mm, with
            # validation and uint32 conversion performed once for this batch.
            port=self.io.array if mapped else None
            deadline=time.monotonic()+.030
            written=0
            try:
                for word in words:
                    if mapped:port[0x6c//4]=word
                    else:self.io.write(0x6c,int(word))
                    written+=1
                    if written%128==0 and time.monotonic()>=deadline:break
                # Commit in one vector operation instead of two NumPy scalar
                # accesses per pixel pair. On I/O failure rebuild the cache.
                committed=addresses[:written]
                self._lcd_pairs[committed]=target[committed]
            except Exception:
                self._invalidate_lcd_update()
                raise
            stop=start+written
            remaining=len(indices)-stop
            self._lcd_pending=(indices,target,stop) if remaining else None
            if not remaining:
                self.io.write(0x68,1);self.io.write(0x6c,0xc0000001|mode)
            return dict(writes=written,remaining=remaining)

    def close_display(self):
        with self.lock:
            if getattr(self,'_framebuffer',None) is not None:
                self._framebuffer.close()
                self._framebuffer=None

    def display_text(self, page, lines, color=2):
        """Write ASCII status text to the existing 64 x 37 character LCD plane."""
        if type(page) is not int or not 0 <= page <= 3 or type(color) is not int or not 0 <= color <= 4:
            raise ValueError("Invalid LCD page or text color")
        if len(lines) > 37:
            raise ValueError("LCD accepts at most 37 text rows")
        rendered = []
        for line in lines:
            if not isinstance(line, str):
                raise ValueError("LCD rows must be strings")
            rendered.append(line.encode("ascii", "replace").decode("ascii")[:64].ljust(64))
        with self.lock:
            self._invalidate_lcd_update()
            if self.io.read(0x0c) & 0x40000000:
                self.io.write(0x6c, 0xc0000000)
            self.io.write(0x68, page)
            for row, line in enumerate(rendered):
                for column, character in enumerate(line):
                    cell = (color << 8) | ord(character)
                    self.io.write(0x6c, (cell << 16) | (row * 64 + column))

    def awg(self, channel, samples, frequency_hz=0.0, phase_degrees=0.0):
        import math
        if channel not in (0, 1) or len(samples) != 256 or any(type(v) is not int or not 0 <= v <= 65535 for v in samples):
            raise ValueError("AWG requires a channel and 256 unsigned 16-bit codes")
        rate = self.io.read(0x30)
        if not math.isfinite(frequency_hz) or not 0 <= frequency_hz <= rate / 2:
            raise ValueError("AWG frequency outside Nyquist range")
        if not math.isfinite(phase_degrees) or not 0 <= phase_degrees < 360:
            raise ValueError("Invalid AWG phase")
        with self.lock:
            self.wait(lambda: not self.io.read(0x84) & (1 << channel))
            if not self.io.read(0xc) & 16:
                raise RuntimeError("DAC MMCM is not locked")
            for i, word in enumerate(samples):
                self.io.write(0x3000 + channel * 0x1000 + 4 * i, word)
            self.io.write(0x8c + 4 * channel, round(frequency_hz / rate * 2**32))
            self.io.write(0x94 + 4 * channel, round(phase_degrees / 360 * 2**32) & 0xffffffff)
            self.io.write(0x88, 1 << channel)
            self.wait(lambda: not self.io.read(0x84) & (1 << channel))

    def awg_frequency(self, channel, frequency_hz, phase_degrees=0.0):
        if channel not in (0, 1) or not math.isfinite(frequency_hz):
            raise ValueError("Invalid AWG channel or frequency")
        rate = self.io.read(0x30)
        if not 0 <= frequency_hz <= rate / 2:
            raise ValueError("AWG frequency outside Nyquist range")
        if not math.isfinite(phase_degrees) or not 0 <= phase_degrees < 360:
            raise ValueError("Invalid AWG phase")
        with self.lock:
            self.wait(lambda: not self.io.read(0x84) & (1 << channel))
            if not self.io.read(0xc) & 16:
                raise RuntimeError("DAC MMCM is not locked")
            self.io.write(0x8c + 4 * channel, round(frequency_hz / rate * 2**32))
            self.io.write(0x94 + 4 * channel, round(phase_degrees / 360 * 2**32) & 0xffffffff)
            self.io.write(0x88, 1 << channel)
            self.wait(lambda: not self.io.read(0x84) & (1 << channel))
