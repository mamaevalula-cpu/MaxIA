"""Log rotation: gzip logs > 50MB, keep 10 rotated files."""
import threading, time, gzip, shutil, os, logging
log = logging.getLogger(__name__)

class LogRotationManager:
    _instance = None

    @classmethod
    def get(cls) -> "LogRotationManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.log_dir = "/root/my_personal_ai/logs"
        self.max_size_mb = 50
        self.keep_count = 10
        self.check_interval = 300  # 5 min
        self._thread: threading.Thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="log-rotation")
        self._thread.start()
        log.info("LogRotationManager started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.rotate_all()
            except Exception as e:
                log.debug("LogRotation error: %s", e)
            time.sleep(self.check_interval)

    def rotate_all(self):
        if not os.path.isdir(self.log_dir):
            return
        for fname in os.listdir(self.log_dir):
            if not fname.endswith(".log"):
                continue
            path = os.path.join(self.log_dir, fname)
            try:
                size_mb = os.path.getsize(path) / (1024 * 1024)
                if size_mb >= self.max_size_mb:
                    self._rotate(path)
                    self._cleanup_old(path)
            except Exception as e:
                log.debug("rotate %s: %s", fname, e)

    def _rotate(self, path: str):
        ts = time.strftime("%Y%m%d_%H%M%S")
        gz_path = f"{path}.{ts}.gz"
        with open(path, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        # Truncate original
        open(path, "w").close()
        log.info("Rotated %s -> %s", path, gz_path)

    def _cleanup_old(self, base_path: str):
        dir_ = os.path.dirname(base_path)
        base = os.path.basename(base_path)
        archives = sorted([
            f for f in os.listdir(dir_)
            if f.startswith(base + ".") and f.endswith(".gz")
        ])
        while len(archives) > self.keep_count:
            old = os.path.join(dir_, archives.pop(0))
            os.remove(old)
            log.info("Removed old log: %s", old)
