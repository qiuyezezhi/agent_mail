"""Queue validation command."""

import json
import sys

from .constants import REQUIRED_FIELDS, STATUSES
from .errors import NotifyError
from .messages import load_message
from .paths import archive_dir, messages_dir, repo_notify_root
from .registry import load_agents
from .storage import ensure_dirs, write_lock
from .utils import print_json


def validate_message(path, location, agents):
    errors = []
    try:
        message = load_message(path)
    except json.JSONDecodeError:
        return [f"{path.name}: invalid JSON"]
    except NotifyError as exc:
        return [str(exc)]

    missing = sorted(REQUIRED_FIELDS - set(message))
    if missing:
        errors.append(f"{path.name}: missing fields: {', '.join(missing)}")

    status = message.get("status")
    if status not in STATUSES:
        errors.append(f"{path.name}: invalid status: {status}")
    if location == "messages" and status == "handled":
        errors.append(f"{path.name}: handled messages must be archived")
    if location == "archive" and status != "handled":
        errors.append(f"{path.name}: archive messages must be handled")

    if message.get("from") not in agents:
        errors.append(f"{path.name}: unknown from agent: {message.get('from')}")
    if message.get("to") not in agents:
        errors.append(f"{path.name}: unknown to agent: {message.get('to')}")
    sequence = message.get("sequence")
    if not isinstance(sequence, int) or sequence < 1:
        errors.append(f"{path.name}: invalid sequence: {sequence}")
    if path.stem != message.get("id"):
        errors.append(f"{path.name}: file name must match message id")
    return errors

def command_lint(_args):
    root = repo_notify_root()
    with write_lock(root):
        ensure_dirs(root)
        errors = []
        try:
            agents = set(load_agents(root))
        except (json.JSONDecodeError, NotifyError) as exc:
            agents = set()
            errors.append(f"agents.json: {exc}")

        for directory, location in ((messages_dir(root), "messages"), (archive_dir(root), "archive")):
            for path in directory.glob("*.json"):
                errors.extend(validate_message(path, location, agents))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print_json({"ok": True})
    return 0
