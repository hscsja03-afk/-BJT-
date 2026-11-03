"""Offline bundle integrity check; never imports PYNQ or touches hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def verify(path):
    path = Path(path).resolve()
    m = json.loads(path.read_text(encoding="utf-8"))
    resolved = []
    for key, suffix in (("bit", ".bit"), ("hwh", ".hwh")):
        item = m[key]
        p = (path.parent / item["path"]).resolve()
        if p.suffix.lower() != suffix or not p.is_file():
            raise ValueError(f"Missing/invalid {key} file")
        if p.stat().st_size == 0 or hashlib.sha256(p.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Empty file or hash mismatch: {key}")
        resolved.append(p)
    if resolved[0].parent != resolved[1].parent or resolved[0].stem != resolved[1].stem:
        raise ValueError("PYNQ requires matching bit/HWH filenames in one directory")
    root = ET.parse(resolved[1]).getroot()
    target = m["peripheral"]
    modules = [x for x in root.iter("MODULE") if x.get("INSTANCE") == target["instance"]]
    if len(modules) != 1:
        raise ValueError("Expected exactly one module instance")
    # HWH MEMRANGE nodes normally live under the PS master, with INSTANCE naming
    # the slave; they need not be children of the target MODULE.
    ranges = [x for x in root.iter("MEMRANGE") if x.get("INSTANCE") == target["instance"]]
    base, size = int(target["base"], 0), int(target["size"], 0)
    if size <= 0 or not any(int(x.get("BASEVALUE", "-1"), 0) == base and
                            int(x.get("HIGHVALUE", "-1"), 0) - base + 1 == size for x in ranges):
        raise ValueError("Expected peripheral address range not found in HWH")
    return {"files_and_address_verified": True, "hardware_validated": False,
            "peripheral": target}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--example", action="store_true")
    args = parser.parse_args()
    if args.example:
        print(json.dumps({"bit": {"path": "demo.bit", "sha256": "replace_with_observed_sha256"},
                          "hwh": {"path": "demo.hwh", "sha256": "replace_with_observed_sha256"},
                          "peripheral": {"instance": "my_ip_0", "base": "0x43c00000", "size": "0x10000"}}, indent=2))
    elif args.manifest:
        print(json.dumps(verify(args.manifest), indent=2))
    else:
        parser.error("Pass a manifest or --example")


if __name__ == "__main__": main()
