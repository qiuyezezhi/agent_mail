"""Repository and runtime paths."""

import subprocess
from pathlib import Path

from .errors import NotifyError


def run_git(args):
    result = subprocess.run(["git", *args], text=True, capture_output=True)
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or "not a git repository")
    return result.stdout.strip()

def repo_notify_root():
    bare = run_git(["rev-parse", "--is-bare-repository"])
    if bare == "true":
        raise NotifyError("bare repositories are not supported")

    common = run_git(["rev-parse", "--git-common-dir"])
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (Path.cwd() / common_path).resolve()
    else:
        common_path = common_path.resolve()

    if common_path.name != ".git":
        raise NotifyError("unsupported git common dir layout; expected a non-bare repository")
    return common_path.parent / ".agent-notify"

def messages_dir(root):
    return root / "messages"

def archive_dir(root):
    return root / "archive"

def agents_path(root):
    return root / "agents.json"

def state_path(root):
    return root / "state.json"

def watcher_state_path(root):
    return root / "watcher-state.json"

def watcher_locks_dir(root):
    return root / "watcher-locks"

def logs_dir(root):
    return root / "logs"
