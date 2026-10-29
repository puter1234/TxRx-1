import subprocess
import sys


def test_native_gil_stall_is_recorded_automatically(tmp_path):
    # ctypes.PyDLL deliberately holds the GIL. A Python watchdog cannot run in
    # this state, while CPython faulthandler must still capture the OCR caller.
    script = '''
import ctypes
from station import vision_trace as trace
trace.STALL_SECONDS = 0.1
with trace.operation(DIRECTORY, 'test_auto'):
    with trace.stage('parseq.forward'):
        ctypes.PyDLL(None).usleep(300000)
'''.replace('DIRECTORY', repr(str(tmp_path)))
    result = subprocess.run([sys.executable, '-c', script], timeout=10, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = next(tmp_path.glob('ocr-*.log')).read_text()
    assert 'BEGIN parseq.forward' in report
    assert 'Timeout (' in report
    assert 'test_native_gil_stall' not in report  # the child, not the pytest parent
    assert 'END parseq.forward' in report


def test_nested_trace_and_exception_keep_original_failure(tmp_path):
    import pytest
    from station.vision_trace import operation, stage
    with pytest.raises(ValueError, match='bad input'):
        with operation(tmp_path, 'test_auto'):
            with operation(tmp_path, 'parseq.load'):
                with stage('load_weights'):
                    raise ValueError('bad input')
    reports = list(tmp_path.glob('ocr-*.log'))
    assert len(reports) == 1
    assert 'ERROR load_weights ValueError: bad input' in reports[0].read_text()
