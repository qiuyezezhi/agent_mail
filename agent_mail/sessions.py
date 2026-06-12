"""Session discovery and safe-resume selection."""

import json
import os
import re
from pathlib import Path

from .constants import CLAUDE_MEM_MARKER
from .errors import NotifyError
from .messages import load_message, message_path
from .storage import read_json
from .utils import process_is_alive


def claude_sessions_dir(project_root):
    project_key = str(project_root).replace(os.sep, "-")
    return Path.home() / ".claude" / "projects" / project_key

def reasonix_sessions_dir():
    return Path.home() / "Library" / "Application Support" / "reasonix" / "sessions"

def codex_sessions_dir():
    return Path.home() / ".codex" / "sessions"

def codex_process_manager_path():
    return Path.home() / ".codex" / "process_manager" / "chat_processes.json"

def collect_json_values(value, key):
    values = []
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if child_key == key and isinstance(child_value, str):
                values.append(child_value)
            values.extend(collect_json_values(child_value, key))
    elif isinstance(value, list):
        for child in value:
            values.extend(collect_json_values(child, key))
    return values

def path_is_within(path, parent):
    try:
        return os.path.commonpath([str(Path(path).resolve()), str(Path(parent).resolve())]) == str(Path(parent).resolve())
    except (OSError, ValueError):
        return False

def session_matches_project(path, project_root):
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    cwd_values = []
    first_json_line = None
    for line in content.splitlines():
        if not line.strip():
            continue
        if first_json_line is None:
            first_json_line = line
        try:
            cwd_values.extend(collect_json_values(json.loads(line), "cwd"))
        except json.JSONDecodeError:
            continue
    if any(".claude-mem/observer-sessions" in cwd for cwd in cwd_values):
        return False
    if not cwd_values:
        if first_json_line and CLAUDE_MEM_MARKER in first_json_line:
            return False
        return True
    return any(path_is_within(cwd, project_root) for cwd in cwd_values)

def sorted_valid_sessions(directory, project_root):
    if not directory.is_dir():
        return []
    candidates = sorted(directory.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [path for path in candidates if session_matches_project(path, project_root)]

def codex_session_matches_project(path, project_root):
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    cwd_values = []
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            cwd_values.extend(collect_json_values(json.loads(line), "cwd"))
        except json.JSONDecodeError:
            continue
    return any(path_is_within(cwd, project_root) for cwd in cwd_values)

def codex_session_candidates(project_root):
    directory = codex_sessions_dir()
    if not directory.is_dir():
        return []
    candidates = {}
    for path in sorted(directory.rglob("rollout-*.jsonl"), key=lambda candidate: candidate.stat().st_mtime, reverse=True):
        if not codex_session_matches_project(path, project_root):
            continue
        session_id = "-".join(path.stem.split("-")[-5:])
        candidates[session_id] = max(candidates.get(session_id, 0), int(path.stat().st_mtime * 1000))
    return sorted(candidates.items(), key=lambda item: (item[1], item[0]), reverse=True)

def load_codex_process_manager():
    path = codex_process_manager_path()
    if not path.is_file():
        return []
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]

def claude_history_path():
    return Path.home() / ".claude" / "history.jsonl"

def claude_active_sessions_dir():
    return Path.home() / ".claude" / "sessions"

def claude_session_candidates(project_root):
    candidates = {}
    history_path = claude_history_path()
    if history_path.is_file():
        for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            project = entry.get("project")
            session_id = entry.get("sessionId")
            timestamp = entry.get("timestamp", 0)
            if (
                isinstance(project, str)
                and isinstance(session_id, str)
                and ".claude-mem/observer-sessions" not in project
                and path_is_within(project, project_root)
            ):
                candidates[session_id] = max(candidates.get(session_id, 0), timestamp if isinstance(timestamp, int) else 0)

    active_dir = claude_active_sessions_dir()
    if active_dir.is_dir():
        for path in active_dir.glob("*.json"):
            try:
                entry = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            cwd = entry.get("cwd")
            session_id = entry.get("sessionId")
            started_at = entry.get("startedAt", 0)
            if (
                isinstance(cwd, str)
                and isinstance(session_id, str)
                and ".claude-mem/observer-sessions" not in cwd
                and path_is_within(cwd, project_root)
            ):
                candidates[session_id] = max(
                    candidates.get(session_id, 0),
                    started_at if isinstance(started_at, int) else 0,
                )

    legacy_sessions = sorted_valid_sessions(claude_sessions_dir(project_root), project_root)
    for path in legacy_sessions:
        candidates[path.stem] = max(candidates.get(path.stem, 0), int(path.stat().st_mtime * 1000))
    return sorted(candidates.items(), key=lambda item: (item[1], item[0]), reverse=True)

def claude_session_is_safe(session_id):
    directory = claude_active_sessions_dir()
    if not directory.is_dir():
        return True
    active_records = []
    for path in directory.glob("*.json"):
        try:
            entry = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if entry.get("sessionId") == session_id and process_is_alive(entry.get("pid")):
            active_records.append(entry)
    if not active_records:
        return True
    return all(entry.get("status") == "idle" for entry in active_records)

def preferred_session_id(message, root):
    match = re.search(r"\bIn reply to ([0-9a-f]{32})\b", message.get("body", ""), flags=re.IGNORECASE)
    if match is None:
        return None
    try:
        original = load_message(message_path(root, match.group(1), include_archive=True))
    except NotifyError:
        return None
    if original.get("from") != message.get("to"):
        return None
    return original.get("source_session_id")

def select_claude_session(project_root, preferred=None):
    candidates = claude_session_candidates(project_root)
    if not candidates:
        return None
    candidate_ids = {session_id for session_id, _timestamp in candidates}
    selected_id = preferred if preferred in candidate_ids else candidates[0][0]
    legacy_path = claude_sessions_dir(project_root) / f"{selected_id}.jsonl"
    return {
        "id": selected_id,
        "path": str(legacy_path) if legacy_path.is_file() else None,
        "resume_arg": selected_id,
        "safe": claude_session_is_safe(selected_id),
    }

def select_reasonix_session(project_root, preferred=None):
    directory = reasonix_sessions_dir()
    if preferred:
        candidates = [Path(preferred)]
        candidates.extend([directory / preferred, directory / f"{preferred}.jsonl"])
        for candidate in candidates:
            if candidate.is_file() and session_matches_project(candidate, project_root):
                return {"id": candidate.stem, "path": str(candidate), "resume_arg": str(candidate)}
    sessions = sorted_valid_sessions(directory, project_root)
    if not sessions:
        return None
    selected = sessions[0]
    return {"id": selected.stem, "path": str(selected), "resume_arg": str(selected)}

def codex_session_is_safe(session_id):
    for entry in load_codex_process_manager():
        if entry.get("conversationId") != session_id:
            continue
        if process_is_alive(entry.get("osPid")):
            return False
    return True

def select_codex_session(project_root, preferred=None):
    candidates = codex_session_candidates(project_root)
    if not candidates:
        return None
    candidate_ids = {session_id for session_id, _timestamp in candidates}
    selected_id = preferred if preferred in candidate_ids else candidates[0][0]
    path = None
    for candidate_path in codex_sessions_dir().rglob(f"rollout-*-{selected_id}.jsonl"):
        if codex_session_matches_project(candidate_path, project_root):
            path = candidate_path
            break
    return {
        "id": selected_id,
        "path": str(path) if path is not None else None,
        "resume_arg": selected_id,
        "safe": codex_session_is_safe(selected_id),
    }

def select_agent_session(agent_type_value, project_root, message, root):
    preferred = preferred_session_id(message, root)
    if agent_type_value == "claude":
        return select_claude_session(project_root, preferred)
    if agent_type_value == "reasonix":
        return select_reasonix_session(project_root, preferred)
    if agent_type_value == "codex":
        return select_codex_session(project_root, preferred)
    return None
