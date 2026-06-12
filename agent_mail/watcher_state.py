"""Watcher state, retries, and per-session locks."""

import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager

from .errors import NotifyError
from .paths import watcher_locks_dir, watcher_state_path
from .storage import atomic_write_json, ensure_dirs, now_iso, read_json, write_lock
from .utils import process_is_alive


def load_watcher_state(root):
    path = watcher_state_path(root)
    if not path.exists():
        return {"in_flight": {}, "retries": {}}
    data = read_json(path)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("in_flight", {}), dict)
        or not isinstance(data.get("retries", {}), dict)
    ):
        raise NotifyError(f"{path}: invalid watcher state")
    return {
        "in_flight": data.get("in_flight", {}),
        "retries": data.get("retries", {}),
    }

def save_watcher_state(root, state):
    atomic_write_json(watcher_state_path(root), state)

def retry_backoff(root, message_id):
    with write_lock(root):
        state = load_watcher_state(root)
        retry = state["retries"].get(message_id)
    if not retry:
        return None
    next_attempt_at = retry.get("next_attempt_at")
    if not isinstance(next_attempt_at, (int, float)) or next_attempt_at <= time.time():
        return None
    return retry

def record_retry_failure(root, message_id, error):
    with write_lock(root):
        state = load_watcher_state(root)
        previous = state["retries"].get(message_id, {})
        attempts = previous.get("attempts", 0) + 1
        delay_seconds = min(300, 5 * (2 ** min(attempts - 1, 6)))
        state["retries"][message_id] = {
            "attempts": attempts,
            "last_error": error,
            "next_attempt_at": time.time() + delay_seconds,
            "updated_at": now_iso(),
        }
        save_watcher_state(root, state)

def clear_retry_failure(root, message_id):
    with write_lock(root):
        state = load_watcher_state(root)
        if message_id in state["retries"]:
            state["retries"].pop(message_id, None)
            save_watcher_state(root, state)

def claude_conversation_is_missing(result):
    output = f"{result.stderr}\n{result.stdout}"
    return "No conversation found with session ID" in output

def resume_lock_name(agent, session_id):
    digest = hashlib.sha256(f"{agent}:{session_id}".encode("utf-8")).hexdigest()[:20]
    return f"{agent}-{digest}"


@contextmanager

def session_resume_lock(root, agent, session_id, message_id):
    ensure_dirs(root)
    name = resume_lock_name(agent, session_id)
    lock_path = watcher_locks_dir(root) / f"{name}.lock"
    acquired = False
    while not acquired:
        try:
            os.mkdir(lock_path)
            acquired = True
        except FileExistsError:
            owner_path = lock_path / "owner.json"
            try:
                owner = read_json(owner_path)
            except (OSError, json.JSONDecodeError):
                owner = {}
            if process_is_alive(owner.get("pid")):
                yield False
                return
            shutil.rmtree(lock_path, ignore_errors=True)

    owner = {
        "agent": agent,
        "session_id": session_id,
        "message_id": message_id,
        "pid": os.getpid(),
        "started_at": now_iso(),
    }
    atomic_write_json(lock_path / "owner.json", owner)
    with write_lock(root):
        state = load_watcher_state(root)
        state["in_flight"][name] = owner
        save_watcher_state(root, state)
    try:
        yield True
    finally:
        with write_lock(root):
            state = load_watcher_state(root)
            current = state["in_flight"].get(name)
            if current and current.get("pid") == os.getpid():
                state["in_flight"].pop(name, None)
                save_watcher_state(root, state)
        shutil.rmtree(lock_path, ignore_errors=True)
