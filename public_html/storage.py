"""Atomic JSON storage and a reentrant, cross-process transaction lock."""
import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / 'data'
_mutex = threading.RLock()
_state = threading.local()


@contextmanager
def transaction():
    with _mutex:
        if getattr(_state, 'depth', 0):
            _state.depth += 1
            try:
                yield
            finally:
                _state.depth -= 1
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / '.write.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _state.depth = 1
            try:
                yield
            finally:
                _state.depth = 0
                fcntl.flock(lock, fcntl.LOCK_UN)


def read_json(filename):
    # Writers replace complete files atomically; an open reader sees either version.
    with (DATA_DIR / filename).open(encoding='utf-8') as handle:
        return json.load(handle)


def write_json(filename, data):
    with transaction():
        descriptor, temporary = tempfile.mkstemp(dir=DATA_DIR, prefix='.json-')
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, DATA_DIR / filename)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def content_revision():
    with transaction():
        import hashlib
        digest = hashlib.sha256()
        for filename in ('books.json', 'cities.json', 'collections.json', 'feed.json', 'home.json', 'mountain_peaks.gpx'):
            path = DATA_DIR / filename
            if path.exists():
                digest.update(path.read_bytes())
        routes_dir = DATA_DIR / 'gpx_routes'
        if routes_dir.exists():
            for path in sorted(routes_dir.glob('*.gpx')):
                digest.update(path.name.encode('utf-8'))
                digest.update(path.read_bytes())
        return digest.hexdigest()
