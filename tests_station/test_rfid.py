import random
import threading
from types import SimpleNamespace
import pytest
from station.rfid import Parser, Frame, Reader, InventoryCancelled, frame, tag_notice


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


def notice(epc="1D44D280281B70D75A8DF0000E114D7A"):
    code = bytes.fromhex(epc)
    pc = ((len(code) // 2) << 11).to_bytes(2, "big")
    return frame(0x22, b"\xd1" + pc + code + b"\x12\x34", 2)


@pytest.fixture
def wire(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("station.rfid.time", SimpleNamespace(
        monotonic=lambda: clock[0], monotonic_ns=lambda: int(clock[0] * 1e9)))

    class Serial:
        def __init__(self):
            self.writes, self.chunks = [], []
            self.reads = 0
            self.on_read = lambda: None
            self.is_open = True

        def write(self, data):
            self.writes.append(data)
            return len(data)

        def reset_input_buffer(self): pass

        def close(self): self.is_open = False

        def read(self, size):
            clock[0] += .02
            self.reads += 1
            self.on_read()
            return self.chunks.pop(0) if self.chunks else b""

    port = Serial()
    reader = Reader("test", serial_factory=lambda **kwargs: port)
    reader.initialized = True
    return reader, port, clock


def test_production_sends_one_round_and_stops_on_first_tag(wire):
    reader, port, clock = wire
    port.chunks = [notice(), notice()]
    result = reader.inventory_once(100)
    assert port.writes == [frame(0x27, b"\x22\x00\x01"), frame(0x28)]
    assert len(result) == 1 and result[0]["count"] == 1
    assert port.reads == 1 and clock[0] == pytest.approx(10.02)


def test_bench_inventory_keeps_its_existing_repeat_window(wire):
    reader, port, _ = wire
    port.chunks = [notice(), notice()]
    result = reader.inventory(100)
    assert port.writes == [frame(0x27, b"\x22\x00\x64"), frame(0x28)]
    assert result[0]["count"] == 2 and port.reads >= 5


@pytest.mark.parametrize("miss_first", [False, True])
@pytest.mark.parametrize("same_chunk", [False, True])
def test_bench_preserves_tags_around_missed_rounds(wire, miss_first, same_chunk):
    reader, port, _ = wire
    replies = [notice(), frame(0xFF, b"\x15", 1)]
    if miss_first:
        replies.reverse()
    replies.append(notice())
    port.chunks = [b"".join(replies)] if same_chunk else replies
    result = reader.inventory(100)
    assert len(result) == 1 and result[0]["count"] == 2
    assert port.reads >= 5 and reader.initialized
    assert port.writes[-1] == frame(0x28)


def test_bench_preserves_distinct_tags_across_missed_rounds(wire):
    reader, port, _ = wire
    epcs = ["1D44D280281B70D75A8DF0000E114D7A", "1234567890ABCDEF1234567890ABCDEF"]
    port.chunks = [notice(epcs[0]), frame(0xFF, b"\x15", 1), notice(epcs[1])]
    assert {tag["epc"] for tag in reader.inventory(100)} == set(epcs)


@pytest.mark.parametrize("read_method", ["inventory_once", "inventory"])
@pytest.mark.parametrize("reply", [b"", frame(0xFF, b"\x15", 1)])
def test_miss_is_retryable(wire, reply, read_method):
    reader, port, _ = wire
    port.chunks = [reply]
    assert getattr(reader, read_method)(100) == []
    assert reader.initialized and port.writes[-1] == frame(0x28)
    port.chunks = [notice()]
    assert len(getattr(reader, read_method)(100)) == 1


def test_single_round_preserves_distinct_tags_in_received_chunk(wire):
    reader, port, _ = wire
    port.chunks = [notice() + notice("1234567890ABCDEF1234567890ABCDEF")]
    assert len(reader.inventory_once(100)) == 2


@pytest.mark.parametrize("read_method", ["inventory_once", "inventory"])
@pytest.mark.parametrize("corrupt", [False, True])
def test_inventory_does_not_hide_reader_or_checksum_errors(wire, corrupt, read_method):
    reader, port, _ = wire
    bad = bytearray(notice())
    bad[-2] ^= 1
    error = bytes(bad) if corrupt else frame(0xFF, b"\x17", 1)
    port.chunks = [notice() + frame(0xFF, b"\x15", 1) + error]
    message = "RFID frame checksum/length error" if corrupt else "RFID inventory error: 17"
    with pytest.raises(IOError, match=message):
        getattr(reader, read_method)(100)
    assert port.writes[-1] == frame(0x28)


@pytest.mark.parametrize("read_method,rounds", [("inventory_once", 1), ("inventory", 100)])
@pytest.mark.parametrize("before_start", [False, True])
def test_inventory_cancellation_stops_without_accepting_a_late_tag(wire, before_start, read_method, rounds):
    reader, port, _ = wire
    cancel = threading.Event()
    port.chunks = [notice()]
    if before_start:
        cancel.set()
    else:
        port.on_read = cancel.set
    with pytest.raises(InventoryCancelled):
        getattr(reader, read_method)(100, cancel)
    assert port.writes == ([] if before_start else [frame(0x27, b"\x22" + rounds.to_bytes(2, "big")), frame(0x28)])
