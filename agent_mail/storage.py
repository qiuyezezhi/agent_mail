"""Filesystem storage helpers."""

import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

from .errors import NotifyError
from .paths import archive_dir, logs_dir, messages_dir, state_path, watcher_locks_dir


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="microseconds")

def ensure_dirs(root):
    root.mkdir(parents=True, exist_ok=True)
    messages_dir(root).mkdir(parents=True, exist_ok=True)
    archive_dir(root).mkdir(parents=True, exist_ok=True)
    watcher_locks_dir(root).mkdir(parents=True, exist_ok=True)
    logs_dir(root).mkdir(parents=True, exist_ok=True)


@contextmanager

def write_lock(root, timeout_seconds=10):
    root.mkdir(parents=True, exist_ok=True)
    lock_dir = root / "lock.d"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.mkdir(lock_dir)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise NotifyError(f"could not acquire notification lock: {lock_dir}")
            time.sleep(0.05)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)

def atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(temp, path)

def atomic_write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)

def read_json(path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def load_state(root):
    path = state_path(root)
    if not path.exists():
        return {"next_sequence": 1}
    data = read_json(path)
    if not isinstance(data, dict):
        raise NotifyError(f"{path}: invalid state")
    next_sequence = data.get("next_sequence")
    if not isinstance(next_sequence, int) or next_sequence < 1:
        raise NotifyError(f"{path}: invalid next_sequence")
    return {"next_sequence": next_sequence}

def save_state(root, state):
    atomic_write_json(state_path(root), state)
