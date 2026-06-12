"""Foreground watcher loop and wakeup dispatch."""

import json
import subprocess
import time
import uuid

from .constants import SUPPORTED_AGENT_TYPES
from .errors import NotifyError
from .messages import load_message
from .paths import logs_dir, messages_dir, repo_notify_root
from .registry import agent_type, load_agent_records
from .sessions import select_agent_session
from .storage import ensure_dirs, now_iso
from .utils import parse_agent_names, print_json
from .watcher_state import (
    claude_conversation_is_missing,
    clear_retry_failure,
    record_retry_failure,
    retry_backoff,
    session_resume_lock,
)


def build_watcher_prompt(message, agent, project_root, current_session_id):
    source_session = message.get("source_session_id") or "not provided"
    return f"""You are {agent}, an agent working in this repository:

{project_root}

The sender's source session id: {source_session}

Read this unread local notification:

agent-notify read --agent {agent} {message['id']}

Handle the request without interrupting any other active turn. When done, send a reply to {message['from']}.
The reply body must begin with "In reply to {message['id']}" so the watcher can route it back to the sender's source session.
Include your current session id on the reply:

agent-notify send --from {agent} --to {message['from']} --source-session-id {current_session_id} --subject "re: {message['subject']}" --body "In reply to {message['id']}

<your result>"

Then mark the original notification handled:

agent-notify handle --agent {agent} {message['id']} --note "Replied to {message['from']} with result."

The notification is not complete until both commands succeed.
"""

def build_resume_command(agent_type_value, session, prompt, project_root):
    if agent_type_value == "claude":
        return [
            "claude",
            "--dangerously-skip-permissions",
            "-r",
            session["resume_arg"],
            "--add-dir",
            str(project_root),
            "--allowedTools",
            "Read,Grep,Glob,Bash(git *),Bash(agent-notify *),Bash(python3 -m unittest tests/test_agent_mail.py),Bash(agent-notify lint)",
            "--max-turns",
            "60",
            "--output-format",
            "json",
            "-p",
            prompt,
        ]
    if agent_type_value == "reasonix":
        return ["reasonix", "run", "--resume", session["resume_arg"], prompt]
    if agent_type_value == "codex":
        return ["codex", "exec", "resume", session["resume_arg"], prompt]
    raise NotifyError(f"watcher does not support agent type: {agent_type_value}")

def build_claude_new_session_command(session_id, prompt, project_root):
    return [
        "claude",
        "--dangerously-skip-permissions",
        "--session-id",
        session_id,
        "--add-dir",
        str(project_root),
        "--allowedTools",
        "Read,Grep,Glob,Bash(git *),Bash(agent-notify *),Bash(python3 -m unittest tests/test_agent_mail.py),Bash(agent-notify lint)",
        "--max-turns",
        "60",
        "--output-format",
        "json",
        "-p",
        prompt,
    ]

def unread_messages_for_agent(root, agent):
    messages = []
    for path in messages_dir(root).glob("*.json"):
        message = load_message(path)
        if message.get("to") == agent and message.get("status") == "unread":
            messages.append(message)
    return sorted(messages, key=lambda message: (message.get("sequence", 0), message.get("id", "")))

def parse_agent_list(value, root):
    if value:
        return parse_agent_names(value)
    return [record["name"] for record in load_agent_records(root) if record["type"] in SUPPORTED_AGENT_TYPES]

def watch_log(root, message):
    ensure_dirs(root)
    with (logs_dir(root) / "watcher.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} {message}\n")

def watch_once(root, agents, timeout_seconds):
    project_root = root.parent.resolve()
    report = {"attempted": [], "failed": [], "skipped": []}
    for agent in agents:
        try:
            agent_type_value = agent_type(root, agent)
        except NotifyError as exc:
            report["skipped"].append({"agent": agent, "reason": str(exc)})
            continue
        if agent_type_value not in SUPPORTED_AGENT_TYPES:
            report["skipped"].append({"agent": agent, "reason": "unsupported agent type"})
            continue
        messages = unread_messages_for_agent(root, agent)
        if not messages:
            continue
        message = messages[0]
        retry = retry_backoff(root, message["id"])
        if retry:
            report["skipped"].append(
                {
                    "agent": agent,
                    "message_id": message["id"],
                    "reason": "retry backoff active",
                    "next_attempt_at": retry["next_attempt_at"],
                }
            )
            continue
        session = select_agent_session(agent_type_value, project_root, message, root)
        if session is None:
            report["skipped"].append(
                {"agent": agent, "message_id": message["id"], "reason": "no safe repository session found"}
            )
            continue
        if not session.get("safe", True):
            report["skipped"].append(
                {
                    "agent": agent,
                    "message_id": message["id"],
                    "session_id": session["id"],
                    "reason": "latest repository session is not safe to resume",
                }
            )
            continue
        with session_resume_lock(root, agent, session["id"], message["id"]) as acquired:
            if not acquired:
                report["skipped"].append(
                    {
                        "agent": agent,
                        "message_id": message["id"],
                        "session_id": session["id"],
                        "reason": "session is already being resumed",
                    }
                )
                continue
            prompt = build_watcher_prompt(message, agent, project_root, session["id"])
            command = build_resume_command(agent_type_value, session, prompt, project_root)
            try:
                result = subprocess.run(
                    command,
                    cwd=project_root,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                )
            except OSError as exc:
                error = str(exc)
                record_retry_failure(root, message["id"], error)
                report["failed"].append(
                    {
                        "agent": agent,
                        "message_id": message["id"],
                        "session_id": session["id"],
                        "returncode": None,
                        "stderr": error,
                    }
                )
                continue
            except subprocess.TimeoutExpired as exc:
                error = str(exc.stderr or f"resume timed out after {timeout_seconds} seconds")
                record_retry_failure(root, message["id"], error)
                report["failed"].append(
                    {
                        "agent": agent,
                        "message_id": message["id"],
                        "session_id": session["id"],
                        "returncode": None,
                        "stderr": error,
                    }
                )
                continue
            entry = {
                "agent": agent,
                "message_id": message["id"],
                "session_id": session["id"],
                "returncode": result.returncode,
            }
            if result.returncode == 0:
                clear_retry_failure(root, message["id"])
                report["attempted"].append(entry)
            elif agent_type_value == "claude" and claude_conversation_is_missing(result):
                new_session_id = str(uuid.uuid4())
                new_prompt = build_watcher_prompt(message, agent, project_root, new_session_id)
                new_command = build_claude_new_session_command(new_session_id, new_prompt, project_root)
                try:
                    fallback = subprocess.run(
                        new_command,
                        cwd=project_root,
                        text=True,
                        capture_output=True,
                        timeout=timeout_seconds,
                    )
                except OSError as exc:
                    error = str(exc)
                    record_retry_failure(root, message["id"], error)
                    report["failed"].append(
                        {
                            "agent": agent,
                            "message_id": message["id"],
                            "session_id": new_session_id,
                            "returncode": None,
                            "stderr": error,
                        }
                    )
                    continue
                except subprocess.TimeoutExpired as exc:
                    error = str(exc.stderr or f"new session timed out after {timeout_seconds} seconds")
                    record_retry_failure(root, message["id"], error)
                    report["failed"].append(
                        {
                            "agent": agent,
                            "message_id": message["id"],
                            "session_id": new_session_id,
                            "returncode": None,
                            "stderr": error,
                        }
                    )
                    continue
                fallback_entry = {
                    "agent": agent,
                    "message_id": message["id"],
                    "session_id": new_session_id,
                    "returncode": fallback.returncode,
                    "fallback_from_session_id": session["id"],
                }
                if fallback.returncode == 0:
                    clear_retry_failure(root, message["id"])
                    report["attempted"].append(fallback_entry)
                else:
                    fallback_entry["stderr"] = (
                        fallback.stderr.strip() or fallback.stdout.strip() or "new session failed"
                    )
                    record_retry_failure(root, message["id"], fallback_entry["stderr"])
                    report["failed"].append(fallback_entry)
            else:
                entry["stderr"] = result.stderr.strip() or result.stdout.strip() or "resume failed"
                record_retry_failure(root, message["id"], entry["stderr"])
                report["failed"].append(entry)
    return report

def command_watch_run(args):
    root = repo_notify_root()
    ensure_dirs(root)
    agents = parse_agent_list(args.agents, root)
    if args.once:
        print_json(watch_once(root, agents, args.timeout))
        return
    watch_log(root, f"watcher started for agents={','.join(agents)} interval={args.interval}")
    while True:
        report = watch_once(root, agents, args.timeout)
        if any(report.values()):
            watch_log(root, json.dumps(report, ensure_ascii=False, sort_keys=True))
        time.sleep(args.interval)
