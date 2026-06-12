"""macOS launchd integration for the watcher."""

import hashlib
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .constants import WATCHER_LABEL_PREFIX
from .errors import NotifyError
from .paths import logs_dir, repo_notify_root
from .storage import atomic_write_bytes, ensure_dirs
from .utils import print_json


WATCHER_PROCESS_NAME = "agent-notify-watcher"


def watcher_label(root):
    digest = hashlib.sha256(str(root.parent.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{WATCHER_LABEL_PREFIX}.{digest}"

def watcher_plist_path(root):
    return Path.home() / "Library" / "LaunchAgents" / f"{watcher_label(root)}.plist"

def watcher_plist_glob():
    return Path.home().joinpath("Library", "LaunchAgents").glob(f"{WATCHER_LABEL_PREFIX}.*.plist")

def watcher_executable_path(root):
    return root / "watcher-bin" / WATCHER_PROCESS_NAME

def ensure_watcher_executable(root):
    path = watcher_executable_path(root)
    target = Path(sys.executable).resolve()
    if path.exists() or path.is_symlink():
        try:
            if path.resolve() == target:
                return path
        except FileNotFoundError:
            pass
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    return path

def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)

def install_watcher(root, agents, interval, timeout):
    if sys.platform != "darwin":
        raise NotifyError("watch install is only supported on macOS")
    ensure_dirs(root)
    label = watcher_label(root)
    plist_path = watcher_plist_path(root)
    log_path = logs_dir(root) / "watcher.log"
    script_path = Path(sys.argv[0]).resolve()
    watcher_executable = ensure_watcher_executable(root)
    program_arguments = [
        str(watcher_executable),
        str(script_path),
        "watch",
        "run",
    ]
    if agents:
        program_arguments.extend(["--agents", agents])
    program_arguments.extend(["--interval", format_number(interval), "--timeout", format_number(timeout)])
    plist = {
        "Label": label,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(root.parent),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
        },
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }
    atomic_write_bytes(plist_path, plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))
    subprocess.run(["launchctl", "unload", str(plist_path)], text=True, capture_output=True)
    loaded = subprocess.run(["launchctl", "load", str(plist_path)], text=True, capture_output=True)
    if loaded.returncode != 0:
        raise NotifyError(loaded.stderr.strip() or f"could not load launch agent: {label}")
    return {
        "installed": True,
        "label": label,
        "plist": str(plist_path),
        "log": str(log_path),
        "executable": str(watcher_executable),
    }

def command_watch_install(args):
    root = repo_notify_root()
    print_json(install_watcher(root, args.agents, args.interval, args.timeout))

def watcher_status(root):
    label = watcher_label(root)
    plist_path = watcher_plist_path(root)
    result = subprocess.run(["launchctl", "list", label], text=True, capture_output=True)
    status = {
        "installed": plist_path.is_file(),
        "loaded": result.returncode == 0,
        "label": label,
        "plist": str(plist_path),
        "log": str(logs_dir(root) / "watcher.log"),
    }
    if plist_path.is_file():
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        args = plist.get("ProgramArguments", [])
        status.update(watcher_config_from_args(args))
    return status


def watcher_config_from_args(args):
    config = {}
    for key, output_key in (("--agents", "agents"), ("--interval", "interval"), ("--timeout", "timeout")):
        if key in args:
            value = args[args.index(key) + 1]
            if output_key in {"interval", "timeout"}:
                try:
                    value = float(value)
                except ValueError:
                    pass
            config[output_key] = value
    return config

def command_watch_status(_args):
    root = repo_notify_root()
    print_json(watcher_status(root))

def uninstall_watcher(root, remove_executable=True):
    label = watcher_label(root)
    plist_path = watcher_plist_path(root)
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], text=True, capture_output=True)
        plist_path.unlink()
    executable = watcher_executable_path(root)
    if remove_executable and (executable.exists() or executable.is_symlink()):
        executable.unlink()
        try:
            executable.parent.rmdir()
        except OSError:
            pass
    return {"installed": False, "loaded": False, "label": label, "plist": str(plist_path)}

def cleanup_watchers(root, dry_run=False):
    if sys.platform != "darwin":
        raise NotifyError("watch cleanup is only supported on macOS")
    current_label = watcher_label(root)
    removed = []
    kept = []
    for plist_path in watcher_plist_glob():
        item = inspect_cleanup_candidate(plist_path, current_label)
        if item["stale"]:
            if not dry_run:
                subprocess.run(["launchctl", "unload", str(plist_path)], text=True, capture_output=True)
                try:
                    plist_path.unlink()
                except FileNotFoundError:
                    pass
            removed.append(item)
        else:
            kept.append(item)
    return {"checked": True, "dry_run": dry_run, "removed": removed, "kept": kept}

def inspect_cleanup_candidate(plist_path, current_label):
    item = {
        "label": plist_path.stem,
        "plist": str(plist_path),
        "current_project": False,
        "stale": False,
        "reason": None,
    }
    try:
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        item.update({"stale": True, "reason": f"invalid plist: {exc}"})
        return item

    label = plist.get("Label") or plist_path.stem
    item["label"] = label
    item["current_project"] = label == current_label
    working_directory = plist.get("WorkingDirectory")
    args = plist.get("ProgramArguments") or []
    if not working_directory or not Path(working_directory).is_dir():
        item.update({"stale": True, "reason": "working directory missing"})
    elif len(args) < 2:
        item.update({"stale": True, "reason": "program arguments missing"})
    elif not Path(args[0]).exists():
        item.update({"stale": True, "reason": "watcher executable missing"})
    elif not Path(args[1]).exists():
        item.update({"stale": True, "reason": "cli script missing"})
    return item

def command_watch_uninstall(_args):
    root = repo_notify_root()
    print_json(uninstall_watcher(root))
