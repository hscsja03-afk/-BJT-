#!/usr/bin/env python3
"""Reliably send the audited PYNQ image to the board's UDP eMMC writer."""
import argparse
import hashlib
import socket
import struct
import sys
import time
import zlib
from pathlib import Path


MAGIC = b"EMMC"
VERSION = 1
HEADER = struct.Struct(">4sBBHIII")
OP_HELLO = 1
OP_BEGIN = 2
OP_DATA = 3
OP_COMMIT = 4
PORT = 5001
HOST_IP = "192.168.0.3"
BOARD_IP = "192.168.0.2"
BLOCK_BYTES = 512
CHUNK_BYTES = 32 * 1024 * 1024
DATA_BYTES = 1472 - HEADER.size
EXPECTED_IMAGE_BYTES = 7_653_556_224
EXPECTED_IMAGE_SHA256 = "d762165b6a0fb2f7bcf2132ebb46c765bfa9f0069fed4c93ced69ac2e7722fdc"


def frame(operation, chunk=0, arg0=0, arg1=0, data=b""):
    return HEADER.pack(MAGIC, operation, VERSION, HEADER.size, chunk, arg0, arg1) + data


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default=r"D:\FPGA\WSL\PYNQ-work\ZYNQ-7020-2.7.0-emmc-fit.img")
    parser.add_argument("--host-ip", default=HOST_IP)
    parser.add_argument("--board-ip", default=BOARD_IP)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=0.25)
    parser.add_argument("--start-chunk", type=int, default=0,
                        help="zero-based chunk to resume from; earlier chunks are already verified")
    parser.add_argument("--probe-only", action="store_true", help="verify image data packets without committing or writing eMMC")
    parser.add_argument("--probe-packets", type=int, default=1024, help="number of image data packets to verify in probe-only mode")
    return parser.parse_args()


def verify_image(path):
    info = path.stat()
    if info.st_size != EXPECTED_IMAGE_BYTES:
        raise RuntimeError(f"Image size mismatch: {info.st_size} != {EXPECTED_IMAGE_BYTES}")
    digest = hashlib.sha256()
    with path.open("rb") as image:
        while True:
            data = image.read(8 * 1024 * 1024)
            if not data:
                break
            digest.update(data)
    actual = digest.hexdigest()
    if actual != EXPECTED_IMAGE_SHA256:
        raise RuntimeError(f"Image SHA-256 mismatch: {actual}")
    return info.st_size, actual


class Sender:
    def __init__(self, host_ip, board_ip, timeout, retries, window):
        self.board = (board_ip, PORT)
        self.timeout = timeout
        self.retries = retries
        self.window = window
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.sock.bind((host_ip, 0))
        self.sock.settimeout(timeout)

    def close(self):
        self.sock.close()

    def request(self, payload, description, timeout=None, retries=None):
        timeout = self.timeout if timeout is None else timeout
        retries = self.retries if retries is None else retries
        for attempt in range(1, retries + 1):
            self.sock.sendto(payload, self.board)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.sock.settimeout(remaining)
                try:
                    reply, source = self.sock.recvfrom(2048)
                except socket.timeout:
                    break
                if source == self.board and reply == payload:
                    return
            print(f"{description}: retry {attempt}/{retries}", flush=True)
        raise TimeoutError(f"No board acknowledgement for {description}")

    def send_window(self, chunk_index, chunk, first_packet, packet_count):
        packets = {}
        for packet_index in range(first_packet, first_packet + packet_count):
            offset = packet_index * DATA_BYTES
            payload = chunk[offset:offset + DATA_BYTES]
            packets[packet_index] = frame(OP_DATA, chunk_index, packet_index, len(payload), payload)
        pending = set(packets)
        for attempt in range(1, self.retries + 1):
            for packet_index in sorted(pending):
                self.sock.sendto(packets[packet_index], self.board)
            deadline = time.monotonic() + self.timeout
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.sock.settimeout(remaining)
                try:
                    reply, source = self.sock.recvfrom(2048)
                except socket.timeout:
                    break
                if source != self.board or len(reply) < HEADER.size:
                    continue
                header = reply[:HEADER.size]
                try:
                    magic, operation, version, header_bytes, reply_chunk, packet_index, length = HEADER.unpack(header)
                except struct.error:
                    continue
                if (magic != MAGIC or operation != OP_DATA or version != VERSION or
                        header_bytes != HEADER.size or reply_chunk != chunk_index or
                        packet_index not in pending):
                    continue
                if reply == packets[packet_index] and length == len(reply) - HEADER.size:
                    pending.remove(packet_index)
            if not pending:
                return
            if attempt < self.retries:
                print(f"chunk={chunk_index + 1} missing_packets={len(pending)} retry={attempt}/{self.retries}", flush=True)
        raise TimeoutError(f"Chunk {chunk_index + 1}: failed to acknowledge packet {min(pending)}")

    def transfer(self, image_path, total_bytes, probe_only=False, probe_packets=1024,
                 start_chunk=0):
        total_sectors = total_bytes // BLOCK_BYTES
        total_chunks = (total_bytes + CHUNK_BYTES - 1) // CHUNK_BYTES
        if start_chunk < 0 or start_chunk >= total_chunks:
            raise RuntimeError(f"Invalid resume chunk {start_chunk}; expected 0..{total_chunks - 1}")
        sent_bytes = start_chunk * CHUNK_BYTES
        started = time.monotonic()
        image = image_path.open("rb")
        try:
            image.seek(sent_bytes)
            self.request(frame(OP_HELLO), "board HELLO")
            print(f"NETWORK_READY board={self.board[0]} host={self.sock.getsockname()[0]}:{self.sock.getsockname()[1]}", flush=True)
            if start_chunk:
                print(f"NETWORK_RESUME_START chunk={start_chunk + 1}/{total_chunks} verified_bytes={sent_bytes}", flush=True)
            for chunk_index in range(start_chunk, total_chunks):
                chunk = image.read(CHUNK_BYTES)
                if not chunk or len(chunk) % BLOCK_BYTES:
                    raise RuntimeError(f"Invalid image chunk {chunk_index + 1}: {len(chunk)} bytes")
                sectors = len(chunk) // BLOCK_BYTES
                lba = chunk_index * (CHUNK_BYTES // BLOCK_BYTES)
                crc = zlib.crc32(chunk) & 0xffffffff
                self.request(frame(OP_BEGIN, chunk_index, lba, sectors), f"chunk {chunk_index + 1} BEGIN")

                packet_count = (len(chunk) + DATA_BYTES - 1) // DATA_BYTES
                probe_count = min(probe_packets, packet_count)
                probe_window = min(self.window, probe_count)
                probe_started = time.monotonic()
                for start in range(0, probe_count, probe_window):
                    amount = min(probe_window, probe_count - start)
                    self.send_window(chunk_index, chunk, start, amount)
                print(f"UDP_PROBE_PASS packets={probe_count} bytes={min(len(chunk), probe_count * DATA_BYTES)} seconds={time.monotonic() - probe_started:.2f}", flush=True)
                if probe_only:
                    print("PROBE_ONLY_COMPLETE eMMC_write=0", flush=True)
                    return

                for start in range(probe_count, packet_count, self.window):
                    amount = min(self.window, packet_count - start)
                    self.send_window(chunk_index, chunk, start, amount)
                    completed_in_chunk = min(len(chunk), (start + amount) * DATA_BYTES)
                    if completed_in_chunk % (4 * 1024 * 1024) < amount * DATA_BYTES:
                        print(f"NETWORK_CHUNK_TRANSFER seq={chunk_index + 1}/{total_chunks} bytes={completed_in_chunk}/{len(chunk)}", flush=True)

                self.request(frame(OP_COMMIT, chunk_index, crc, sectors),
                             f"chunk {chunk_index + 1} COMMIT/readback", timeout=30.0, retries=20)
                sent_bytes += len(chunk)
                elapsed = time.monotonic() - started
                rate = sent_bytes / max(elapsed, 0.001) / (1024 * 1024)
                eta = (total_bytes - sent_bytes) / max(sent_bytes / max(elapsed, 0.001), 1) / 60
                print(f"EMMC_CHUNK_VERIFIED seq={chunk_index + 1}/{total_chunks} lba={lba} sectors={sectors} crc32={crc:08x} bytes={sent_bytes}/{total_bytes} rate={rate:.2f}MiB/s eta={eta:.1f}min", flush=True)
                del chunk
            if image.read(1):
                raise RuntimeError("Image contains unexpected trailing bytes")
            if sent_bytes != total_bytes or total_sectors * BLOCK_BYTES != total_bytes:
                raise RuntimeError("Transferred byte count does not match the audited image")
            print(f"HOST_IMAGE_TRANSFER_COMPLETE bytes={sent_bytes} chunks={total_chunks}", flush=True)
        finally:
            image.close()


def main():
    args = parse_args()
    if args.window < 1 or args.window > 16:
        raise RuntimeError("--window must be between 1 and 16 (board RX ring depth)")
    image_path = Path(args.image)
    total_bytes, digest = verify_image(image_path)
    print(f"IMAGE_VERIFIED path={image_path} bytes={total_bytes} sha256={digest}", flush=True)
    sender = Sender(args.host_ip, args.board_ip, args.timeout, args.retries, args.window)
    try:
        if args.probe_packets < 1:
            raise RuntimeError("--probe-packets must be positive")
        sender.transfer(image_path, total_bytes, args.probe_only, args.probe_packets,
                       start_chunk=args.start_chunk)
    finally:
        sender.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"NETWORK_WRITE_ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
