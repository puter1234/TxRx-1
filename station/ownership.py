"""OS-held single owner of one station data directory, released even after process exit."""

import os


class Ownership:
    def __init__(self, path):
        self.file = path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError(
                "이 운영 데이터로 이미 실행 중인 서버가 있습니다."
            ) from exc

    def close(self):
        self.file.close()
