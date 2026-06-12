"""Notification message lifecycle commands."""

import json
import sys
import uuid
from pathlib import Path

from .errors import NotifyError
from .paths import archive_dir, messages_dir, repo_notify_root
from .registry import require_agent
from .storage import atomic_write_json, ensure_dirs, load_state, now_iso, read_json, save_state, write_lock
from .utils import print_json
from .watcher_state import clear_retry_failure


def message_path(root, message_id, include_archive=True):
    active = messages_dir(root) / f"{message_id}.json"
    if active.exists():
        return active
    archived = archive_dir(root) / f"{message_id}.json"
    if include_archive and archived.exists():
        return archived
    raise NotifyError(f"message not found: {message_id}")

def load_message(path):
    data = read_json(path)
    if not isinstance(data, dict):
        raise NotifyError(f"{path}: message must be a JSON object")
    return data

def summarize(message):
    return {
        "id": message["id"],
        "from": message["from"],
        "to": message["to"],
        "status": message["status"],
        "sequence": message["sequence"],
        "subject": message["subject"],
        "created_at": message["created_at"],
        "updated_at": message["updated_at"],
        "read_at": message["read_at"],
        "handled_at": message["handled_at"],
    }

def load_all_messages(root):
    messages = []
    for directory in (messages_dir(root), archive_dir(root)):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            messages.append(load_message(path))
    return messages

def sort_messages(messages):
    return sorted(messages, key=lambda msg: (msg.get("sequence", 0), msg.get("updated_at") or "", msg.get("id") or ""), reverse=True)

def command_send(args):
    message = send_message(
        args.sender,
        args.to,
        args.subject,
        read_body(args),
        source_session_id=args.source_session_id,
    )
    print_json(message)

def send_message(sender, to, subject, body, source_session_id=None):
    root = repo_notify_root()
    with write_lock(root):
        ensure_dirs(root)
        require_agent(root, sender)
        require_agent(root, to)
        state = load_state(root)
        sequence = state["next_sequence"]
        state["next_sequence"] = sequence + 1
        save_state(root, state)
        timestamp = now_iso()
        message = {
            "id": uuid.uuid4().hex,
            "from": sender,
            "to": to,
            "status": "unread",
            "sequence": sequence,
            "subject": subject,
            "body": body,
            "source_session_id": source_session_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "read_at": None,
            "handled_at": None,
            "handled_note": None,
        }
        atomic_write_json(messages_dir(root) / f"{message['id']}.json", message)
    return message

def read_body(args):
    if args.body is not None:
        return args.body
    if args.body_file is None:
        return ""
    if args.body_file == "-":
        return sys.stdin.read()
    return Path(args.body_file).read_text(encoding="utf-8")

def command_inbox(args):
    root = repo_notify_root()
    ensure_dirs(root)
    require_agent(root, args.agent)
    messages = [
        summarize(load_message(path))
        for path in messages_dir(root).glob("*.json")
        if load_message(path).get("to") == args.agent
    ]
    print_json(sort_messages(messages))

def command_sent(args):
    root = repo_notify_root()
    ensure_dirs(root)
    require_agent(root, args.agent)
    messages = [summarize(message) for message in load_all_messages(root) if message.get("from") == args.agent]
    messages = sort_messages(messages)
    if not args.all:
        messages = messages[:20]
    print_json(messages)

def command_read(args):
    root = repo_notify_root()
    with write_lock(root):
        ensure_dirs(root)
        require_agent(root, args.agent)
        path = message_path(root, args.message_id, include_archive=False)
        message = load_message(path)
        if message.get("to") != args.agent:
            raise NotifyError("message is not addressed to this agent")
        if message.get("status") == "unread":
            timestamp = now_iso()
            message["status"] = "read"
            message["read_at"] = timestamp
            message["updated_at"] = timestamp
            atomic_write_json(path, message)
    print_json(message)

def command_handle(args):
    root = repo_notify_root()
    with write_lock(root):
        ensure_dirs(root)
        require_agent(root, args.agent)
        path = message_path(root, args.message_id, include_archive=False)
        message = load_message(path)
        if message.get("to") != args.agent:
            raise NotifyError("message is not addressed to this agent")
        timestamp = now_iso()
        if message.get("read_at") is None:
            message["read_at"] = timestamp
        message["status"] = "handled"
        message["handled_at"] = timestamp
        message["updated_at"] = timestamp
        if args.note is not None:
            message["handled_note"] = args.note
        archive_path = archive_dir(root) / path.name
        atomic_write_json(archive_path, message)
        path.unlink()
    clear_retry_failure(root, args.message_id)
    print_json(message)
