import random
import pytest
from station.rfid import Parser, Frame, frame, tag_notice


def test_fragmented_noise_and_multiple_frames():
    rng = random.Random(37)
    messages = [frame(0x08, b"\x06", 1), frame(0x07, b"\0", 1)]
    data = b"noise" + b"".join(messages)
    parser = Parser()
    results = []
    while data:
        n = rng.randint(1, 4)
        results += parser.feed(data[:n])
        data = data[n:]
    assert results == [Frame(1, 0x08, b"\x06"), Frame(1, 0x07, b"\0")]


def test_bad_checksum_length_and_128_bit_epc():
    epc = bytes.fromhex("1D44D280281B70D75A8DF0000E114D7A")
    pc = (8 << 11).to_bytes(2, "big")
    valid = frame(0x22, b"\xd1" + pc + epc + b"\x12\x34", 2)
    bad = bytearray(valid)
    bad[-2] ^= 1
    p = Parser()
    result = p.feed(bytes(bad) + valid)
    assert p.errors and len(result) == 1
    tag = tag_notice(result[0])
    assert tag["epc"] == epc.hex().upper() and tag["rssi"] == -47
    with pytest.raises(ValueError):
        tag_notice(Frame(2, 0x22, b"\xd1" + pc + epc[:-1] + b"\0\0"))


def test_inventory_wire_frame_fixture():
    assert frame(0x27, b"\x22\x00\x64").hex().upper() == "BB00270003220064B07E"
    assert frame(0x28).hex().upper() == "BB00280000287E"


def test_buffer_bounded_under_corruption():
    p = Parser()
    p.feed(b"\xbb\x00\x00\xff\xff" * 10000)
    assert len(p.buffer) <= 1024 and p.errors
