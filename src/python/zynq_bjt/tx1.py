"""DAC60501 on the PL open-drain I2C register. No output on import/init.

The MMIO register's bits 0/1 release SCL/SDA; bits 8/9 read their levels.
Only low drive or high impedance is permitted by the RTL IOBUF contract.
"""
import time


class Tx1:
    def __init__(self, mmio, pause=time.sleep):
        self.io, self.pause = mmio, pause
        self.released = 3
        self.ready = False
        self.pending_code = None

    def pins(self, value):
        self.released = value & 3
        self.io.write(0x40, self.released)

    def lines(self): return (self.io.read(0x40) >> 8) & 3
    def half(self): self.pause(.000002)

    def high(self):
        self.pins(self.released | 1)
        for _ in range(100):
            self.half()
            if self.lines() & 1: return
        raise TimeoutError("TX1 SCL is held low")

    def low(self): self.pins(self.released & ~1); self.half()

    def start(self):
        self.pins(self.released | 2); self.half(); self.high()
        if not self.lines() & 2: raise RuntimeError("TX1 SDA is held low")
        self.pins(self.released & ~2); self.half(); self.low()

    def stop(self):
        self.pins(0); self.half()
        try:
            self.high()
        finally:
            self.pins(3); self.half()
        if self.lines() != 3: raise RuntimeError("TX1 bus did not return idle")

    def send(self, value):
        for shift in range(7, -1, -1):
            self.pins((self.released & 1) | (((value >> shift) & 1) << 1))
            self.half(); self.high(); self.low()
        self.pins(self.released | 2); self.half(); self.high()
        try:
            if self.lines() & 2: raise RuntimeError("TX1 I2C NACK")
        finally: self.low()

    def receive(self, ack):
        self.pins(self.released | 2); self.half()
        result = 0
        for _ in range(8):
            self.high(); result = (result << 1) | ((self.lines() >> 1) & 1); self.low()
        self.pins((self.released & 1) | (0 if ack else 2))
        self.half(); self.high(); self.low(); self.pins(self.released | 2)
        return result

    def transfer(self, register, value=None):
        if type(register) is not int or not 0 <= register <= 255:
            raise ValueError("Invalid TX1 register")
        if value is not None and (type(value) is not int or not 0 <= value <= 65535):
            raise ValueError("TX1 register value must be 16-bit")
        primary = None
        try:
            self.start(); self.send(0x90); self.send(register)
            if value is None:
                self.start(); self.send(0x91)
                return (self.receive(True) << 8) | self.receive(False)
            self.send(value >> 8); self.send(value & 255)
        except BaseException as error:
            primary = error
            raise
        finally:
            try: self.stop()
            except Exception as error:
                if primary is None: raise
                raise RuntimeError(f"{primary}; TX1 STOP also failed: {error}") from primary

    def verified(self, register, value):
        masks = {2: 1, 3: 0x0101, 4: 0x0101, 8: 0xfff0}
        mask = masks[register]
        before = self.transfer(register)
        self.transfer(register, (before & ~mask) | (value & mask))
        got = self.transfer(register)
        if (got & mask) != (value & mask):
            raise RuntimeError(f"TX1 register {register} readback mismatch: {got:04x}")

    def initialize_muted(self):
        self.ready = False
        self.pending_code = None
        if self.io.read(0x44) != 0x54583101:
            raise ValueError("TX1 PL peripheral ID mismatch")
        self.pins(3); self.half()
        if self.lines() != 3: raise RuntimeError("TX1 I2C lines are not idle")
        if self.transfer(1) != 0x2195: raise ValueError("DAC60501 device ID mismatch")
        self.verified(3, 1)
        self.verified(4, 0x0101)
        self.verified(2, 0)
        # On this board two DATA writes during one power-down interval latch
        # the first analog value while later DATA readbacks appear correct.
        # Keep the requested initial zero in software until the single commit
        # immediately before enable. See tx1_isolation_*_20261030 reports.
        if self.transfer(7) & 1: raise RuntimeError("TX1 reference alarm")
        self.ready = True
        self.pending_code = 0

    def code(self, code):
        if not self.ready: raise RuntimeError("TX1 is not initialized")
        if type(code) is not int or not 0 <= code <= 4095: raise ValueError("TX1 code outside 0..4095")
        if self.transfer(3) & 1:
            self.pending_code = code
        else:
            self.verified(8, code << 4)
            self.pending_code = None

    def enable(self, enabled):
        if not self.ready: raise RuntimeError("TX1 is not initialized")
        if type(enabled) is not bool: raise ValueError("TX1 enable must be boolean")
        powered_down = bool(self.transfer(3) & 1)
        if enabled and powered_down:
            # Exactly one DATA write per muted interval; repeated GUI Apply
            # operations only replace pending_code above.
            code = self.pending_code
            if code is None: code = self.transfer(8) >> 4
            try:
                self.verified(8, code << 4)
                self.verified(3, 0)
            except Exception:
                # A partially accepted DATA write makes retrying uncertain.
                # Invalidate instead of performing a second DATA commit.
                self.ready = False
                raise
            self.pending_code = None
        elif not enabled and not powered_down:
            self.verified(3, 1)

    def state(self):
        if not self.ready: raise RuntimeError("TX1 is not initialized")
        enabled = not bool(self.transfer(3) & 1)
        actual = self.transfer(8) >> 4
        pending = not enabled and self.pending_code is not None
        return {"enabled": enabled, "code": self.pending_code if pending else actual,
                "device_code": actual,
                "code_basis": "pending_until_enabled" if pending else "device_register_readback",
                "reference_alarm": bool(self.transfer(7) & 1)}
