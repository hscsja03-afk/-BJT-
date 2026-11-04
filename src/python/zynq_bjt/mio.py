"""Linux MIO GPIO adapter. Construction is explicit and exports owned lines.

GPIO numbering uses PYNQ's chip base + physical MIO, with NO EMIO +54 offset.
Verify SLCR mux and bank voltage before claiming any ADDA line.
"""
from pathlib import Path
import time

PINS = (7, 8, 9, 10, 11, 12, 13, 29, 30, 31, 32, 33)
# gpio-zynq.c (xilinx-v2020.2), zynq_gpio_dir_in: bank 0 pins 7/8
# reject input direction with -EINVAL. They are SCLK/MOSI on this carrier.
OUTPUT_ONLY = frozenset((7, 8))
INACTIVE = {7: 0, 8: 0, 10: 1, 11: 0, 12: 0, 13: 1,
            29: 0, 30: 0, 31: 1, 32: 1, 33: 1}


class Mio:
    def __init__(self, slcr, gpio_base, sysfs="/sys/class/gpio"):
        self.root = Path(sysfs)
        self.base = int(gpio_base)
        self.owned = []
        self.directions = {}
        self.levels = dict(INACTIVE)
        self.preflight(slcr, self.base, self.root)
        try:
            for pin in PINS:
                (self.root / "export").write_text(str(self.base + pin))
                self.owned.append(pin)
                end = time.monotonic() + 1
                while not (self.path(pin) / "direction").exists():
                    if time.monotonic() >= end: raise TimeoutError(f"MIO{pin} export failed")
                    time.sleep(.001)
                if pin not in OUTPUT_ONLY:
                    (self.path(pin) / "direction").write_text("in")
                    self.directions[pin] = False
                else:
                    # Leave the direction untouched until translator enables
                    # and chip selects have been set inactive below.
                    self.directions[pin] = None
            # Translator enables stay inactive (HIGH) during all other setup.
            for pin in (32, 33, 10, 13, 31, 7, 8, 11, 12, 29, 30):
                self.output(pin, True)
        except BaseException as error:
            try:
                self.close()
            except Exception as cleanup:
                raise RuntimeError(f"GPIO initialization failed ({error}); {cleanup}") from error
            raise

    def path(self, pin): return self.root / f"gpio{self.base + pin}"

    @staticmethod
    def preflight(slcr, gpio_base, sysfs="/sys/class/gpio"):
        """Read PS pin settings/ownership without exporting or driving GPIO.

        This cannot identify the physical baseboard or reserve GPIO lines.
        Construction repeats the checks immediately before claiming them.
        """
        root, base = Path(sysfs), int(gpio_base)
        for pin in PINS:
            reg = slcr.read(4 * pin)
            if reg & 0xfe or ((reg >> 9) & 7) != (3 if pin < 16 else 1):
                raise RuntimeError(f"MIO{pin} mux or IO voltage differs from the board contract")
            if (root / f"gpio{base + pin}").exists():
                raise RuntimeError(f"MIO{pin} is already exported; do not take another application's GPIO")

    def write(self, pin, value):
        if pin not in self.owned or value not in (0, 1): raise ValueError("Invalid owned GPIO/value")
        self.levels[pin] = int(value)
        if self.directions[pin]: (self.path(pin) / "value").write_text(str(int(value)))

    def read(self, pin):
        if pin not in self.owned: raise ValueError("GPIO is not owned")
        return int((self.path(pin) / "value").read_text().strip())

    def output(self, pin, enabled):
        if pin not in self.owned: raise ValueError("GPIO is not owned")
        if pin in OUTPUT_ONLY and not enabled:
            raise ValueError(f"MIO{pin} is output-only on Zynq; input direction is unsupported")
        # 'high'/'low' switches direction and preloads the value atomically.
        mode = ("high" if self.levels.get(pin, 0) else "low") if enabled else "in"
        (self.path(pin) / "direction").write_text(mode)
        self.directions[pin] = bool(enabled)

    def close(self):
        errors = []
        remaining = []
        for pin in reversed(self.owned):
            # Unexport releases the sysfs ownership, not the electrical state.
            # Keep SCLK/MOSI at their idle LOW; input is illegal for MIO7/8.
            mode = "low" if pin in OUTPUT_ONLY else "in"
            try:
                (self.path(pin) / "direction").write_text(mode)
            except OSError as error: errors.append(f"MIO{pin} {mode}: {error}")
            # Even if changing direction failed, still attempt to release it.
            try:
                (self.root / "unexport").write_text(str(self.base + pin))
            except OSError as error:
                errors.append(f"MIO{pin} unexport: {error}")
                remaining.append(pin)
            else:
                self.directions.pop(pin, None)
        self.owned = list(reversed(remaining))
        if errors: raise RuntimeError("GPIO release unconfirmed: " + "; ".join(errors))

    @classmethod
    def preflight_from_pynq(cls):
        from pynq import GPIO, MMIO
        cls.preflight(MMIO(0xf8000700, 0x100), GPIO.get_gpio_base())

    @classmethod
    def from_pynq(cls):
        from pynq import GPIO, MMIO
        return cls(MMIO(0xf8000700, 0x100), GPIO.get_gpio_base())
