"""Bounded YRM UART frame parser and reader. Wire protocol needs unit-specific FAT.

The handover fixes inventory 0x27/tag notice 0x22. Other command/framing values
use the BB/7E YRM dialect and stay behind rfid_protocol_verified until checked
against the supplied reader's command manual and captured responses.
"""

from __future__ import annotations
from dataclasses import dataclass
import statistics
import threading
import time


@dataclass(frozen=True)
class Frame:
    kind: int
    command: int
    payload: bytes


def frame(command: int, payload: bytes = b"", kind: int = 0):
    if len(payload) > 512:
        raise ValueError("RFID frame too long")
    body = bytes([kind, command]) + len(payload).to_bytes(2, "big") + payload
    return b"\xbb" + body + bytes([sum(body) & 255, 0x7E])


class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data: bytes):
        self.buffer.extend(data)
        if len(self.buffer) > 8192:
            self.errors += 1
            self.buffer = self.buffer[-1024:]
        frames = []
        while len(self.buffer) >= 7:
            if self.buffer[0] != 0xBB:
                del self.buffer[0]
                continue
            size = int.from_bytes(self.buffer[3:5], "big")
            if size > 512:
                self.errors += 1
                del self.buffer[0]
                continue
            length = size + 7
            if len(self.buffer) < length:
                break
            raw = self.buffer[:length]
            if raw[-1] != 0x7E or sum(raw[1:-2]) & 255 != raw[-2]:
                self.errors += 1
                del self.buffer[0]
                continue
            frames.append(Frame(raw[1], raw[2], bytes(raw[5:-2])))
            del self.buffer[:length]
        return frames


def tag_notice(message: Frame):
    if message.kind != 2 or message.command != 0x22:
        raise ValueError("Not a tag notice")
    p = message.payload
    if len(p) < 7:
        raise ValueError("Short tag notice")
    pc = int.from_bytes(p[1:3], "big")
    epc_bytes = ((pc >> 11) & 31) * 2
    if epc_bytes == 0 or len(p) != epc_bytes + 5:
        raise ValueError("EPC/PC length mismatch")
    return {
        "epc": p[3 : 3 + epc_bytes].hex().upper(),
        "rssi": int.from_bytes(p[:1], "big", signed=True),
        "pc": pc,
        "air_crc": p[-2:].hex().upper(),
        "mono_ns": time.monotonic_ns(),
    }


class Reader:
    def __init__(self, port, serial_factory=None):
        if serial_factory is None:
            import serial

            serial_factory = serial.Serial
        self.port = serial_factory(
            port=port,
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.02,
            write_timeout=0.2,
            exclusive=True,
        )
        self.parser = Parser()
        self.lock = threading.Lock()
        self.initialized = False
        self.last_error = None

    def _send(self, command, payload=b""):
        data = frame(command, payload)
        if self.port.write(data) != len(data):
            raise IOError("Incomplete RFID write")

    def _response(self, command, payload=b"", timeout=0.6):
        self.parser = Parser()
        self.port.reset_input_buffer()
        self._send(command, payload)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in self.parser.feed(self.port.read(512)):
                if m.kind == 1 and m.command == 0xFF:
                    raise IOError("RFID command error: " + m.payload.hex())
                if m.kind == 1 and m.command == command:
                    return m.payload
        raise TimeoutError(f"RFID response timeout: {command:02X}")

    def initialize(self):
        with self.lock:
            self._response(0x08)
            if self._response(0x07, b"\x06") != b"\x00":
                raise IOError("RFID region SET rejected")
            if self._response(0x08) != b"\x06":
                raise IOError("RFID region GET mismatch")
            if self._response(0xB6, (2000).to_bytes(2, "big")) != b"\x00":
                raise IOError("RFID power SET rejected")
            if self._response(0xB7) != (2000).to_bytes(2, "big"):
                raise IOError("RFID power GET mismatch")
            self.initialized = True

    def inventory(self, window_ms: int, cancel: threading.Event | None = None):
        if not self.initialized:
            raise RuntimeError("RFID initialization required")
        with self.lock:
            self.parser = Parser()
            self.port.reset_input_buffer()
            self._send(0x27, b"\x22\x00\x64")
            deadline = time.monotonic() + window_ms / 1000
            tags = {}
            try:
                while time.monotonic() < deadline:
                    if cancel and cancel.is_set():
                        raise RuntimeError("RFID inventory cancelled")
                    for m in self.parser.feed(self.port.read(512)):
                        if m.kind == 1 and m.command == 0xFF:
                            # No-tag/error responses are not a successful inventory.
                            raise IOError("RFID inventory error: " + m.payload.hex())
                        if m.kind == 2 and m.command == 0x22:
                            tag = tag_notice(m)
                            epc = tag["epc"]
                            record = tags.setdefault(
                                epc,
                                {"epc": epc, "samples": [], "first_ns": tag["mono_ns"]},
                            )
                            record["samples"].append(tag["rssi"])
                            record["last_ns"] = tag["mono_ns"]
                if self.parser.errors:
                    raise IOError("RFID frame checksum/length error")
            finally:
                self._send(0x28)
            return [
                {
                    "epc": epc,
                    "count": len(r["samples"]),
                    "max_rssi": max(r["samples"]),
                    "median_rssi": statistics.median(r["samples"]),
                    "first_ns": r["first_ns"],
                    "last_ns": r["last_ns"],
                }
                for epc, r in tags.items()
            ]

    def close(self):
        with self.lock:
            try:
                self._send(0x28)
            finally:
                self.port.close()
