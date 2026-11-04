"""A single pending LCD frame; MMIO stays on the measurement worker thread."""
import base64
import threading
import time
import zlib


def decode_pixels(request):
    native = request.get('native', False)
    if type(native) is not bool:
        raise ValueError('Invalid LCD resolution')
    encoded = request.get('pixels')
    if not encoded:
        return None, native
    data = base64.b64decode(encoded, validate=True)
    decoder = zlib.decompressobj()
    count = 1024*600 if native else 512*300
    pixel_format=request.get('pixel_format','indexed4')
    if pixel_format not in ('indexed4','rgb565') or pixel_format=='rgb565' and not native:
        raise ValueError('Invalid LCD pixel format')
    if pixel_format=='rgb565':count*=2
    pixels = decoder.decompress(data, count+1)
    if (not decoder.eof or decoder.unconsumed_tail or decoder.unused_data
            or len(pixels) != count or pixel_format=='indexed4' and max(pixels) > 15):
        raise ValueError('Invalid LCD compressed frame')
    return pixels, native


class ScanDisplay:
    def __init__(self, core, stream_id, native, emit):
        self.core, self.stream_id, self.native, self.emit = core, stream_id, native, emit
        self.lock = threading.Lock()
        self.pending = None
        self.closed = False
        self.remaining = 1  # Finish the initial frame prepared before the scan.
        self.last_pump = 0

    def offer(self, request):
        # The receive thread validates and replaces a mailbox, never touches MMIO.
        pixels, native = decode_pixels(request)
        with self.lock:
            accepted = not self.closed and request.get('stream_id') == self.stream_id
            if accepted:
                if native != self.native:
                    raise ValueError('LCD scan resolution changed')
                if pixels is not None:
                    self.pending = pixels
        return dict(stream=True, accepted=accepted)

    def pump(self):
        if self.closed or time.monotonic()-self.last_pump < .04:
            return
        self.last_pump = time.monotonic()
        pixels = None
        with self.lock:
            # Finish each frame before adopting the latest replacement. This
            # prevents a growing curve from starving the bottom of the screen.
            if not self.remaining:
                pixels, self.pending = self.pending, None
        if pixels is None and not self.remaining:
            return
        try:
            update = self.core.display_update(pixels, 8192, native=self.native)
            self.remaining = update['remaining']
        except Exception as error:
            self.close()
            self.emit('log', 'LCD 扫描画面暂停：'+str(error))

    def close(self):
        with self.lock:
            self.closed = True
            self.pending = None


class DisplayCancel:
    """Use settling waits for bounded display work, retaining cancellation."""
    def __init__(self, event, display):
        self.event, self.display = event, display

    def is_set(self):
        return self.event.is_set()

    def wait(self, seconds):
        deadline = time.monotonic()+seconds
        while not self.event.is_set():
            self.display.pump()
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                return self.event.is_set()
            if self.event.wait(min(.05, remaining)):
                return True
        return True
