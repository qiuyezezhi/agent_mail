"""Windows Task Scheduler integration for the watcher."""

import csv
import hashlib
import io
import subprocess
import sys
from pathlib import Path

from .errors import NotifyError
from .paths import logs_dir
from .storage import atomic_write_bytes, ensure_dirs


WATCHER_TASK_PREFIX = "DPLake-agent-notify-watcher"


def watcher_label(root):
    digest = hashlib.sha256(str(root.parent.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{WATCHER_TASK_PREFIX}-{digest}"


def launcher_path(root):
    return root / "watcher-task.ps1"


def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _quote_powershell(value):
    return str(value).replace("'", "''")


def _build_launcher(root, agents, interval, timeout):
    project_root = root.parent
    script_path = project_root / "bin" / "agent-notify.ps1"
    log_path = logs_dir(root) / "watcher.log"
    args = [
        "watch",
        "run",
    ]
    if agents:
        args.extend(["--agents", agents])
    args.extend(["--interval", format_number(interval), "--timeout", format_number(timeout)])
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$tool = '{_quote_powershell(script_path)}'",
        f"$log = '{_quote_powershell(log_path)}'",
        "$args = @(",
    ]
    lines.extend(f"    '{_quote_powershell(arg)}'" for arg in args)
    lines.extend(
        [
            ")",
            "& $tool @args *>> $log",
            "exit $LASTEXITCODE",
            "",
        ]
    )
    return "\n".join(lines)


def _run_schtasks(args):
    return subprocess.run(["schtasks", *args], text=True, capture_output=True)


def install_watcher(root, agents, interval, timeout):
    if sys.platform != "win32":
        raise NotifyError("watch install is only supported on Windows")
    ensure_dirs(root)
    label = watcher_label(root)
    path = launcher_path(root)
    log_path = logs_dir(root) / "watcher.log"
    atomic_write_bytes(path, _build_launcher(root, agents, interval, timeout).encode("utf-8"))
    command = (
        f'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "{path}"'
    )
    result = _run_schtasks(["/Create", "/SC", "ONLOGON", "/TN", label, "/TR", command, "/F"])
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or f"could not create scheduled task: {label}")
    return {
        "installed": True,
        "loaded": True,
        "label": label,
        "launcher": str(path),
        "log": str(log_path),
        "scheduler": "taskschd",
    }


def watcher_status(root):
    if sys.platform != "win32":
        raise NotifyError("watch status is only supported on Windows")
    label = watcher_label(root)
    path = launcher_path(root)
    result = _run_schtasks(["/Query", "/TN", label, "/FO", "LIST", "/V"])
    status = {
        "installed": path.is_file(),
        "loaded": result.returncode == 0,
        "label": label,
        "launcher": str(path),
        "log": str(logs_dir(root) / "watcher.log"),
        "scheduler": "taskschd",
    }
    if path.is_file():
        status.update(watcher_config_from_launcher(path))
    return status


def watcher_config_from_launcher(path):
    config = {}
    args = []
    in_args = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "$args = @(":
            in_args = True
            continue
        if in_args and stripped == ")":
            break
        if in_args and stripped.startswith("'") and stripped.endswith("'"):
            args.append(stripped[1:-1].replace("''", "'"))
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


def uninstall_watcher(root, remove_executable=True):
    if sys.platform != "win32":
        raise NotifyError("watch uninstall is only supported on Windows")
    label = watcher_label(root)
    path = launcher_path(root)
    if path.exists():
        result = _run_schtasks(["/Delete", "/TN", label, "/F"])
        if result.returncode != 0:
            raise NotifyError(result.stderr.strip() or f"could not delete scheduled task: {label}")
        if remove_executable:
            path.unlink()
    return {
        "installed": False,
        "loaded": False,
        "label": label,
        "launcher": str(path),
        "scheduler": "taskschd",
    }


def cleanup_watchers(root, dry_run=False):
    if sys.platform != "win32":
        raise NotifyError("watch cleanup is only supported on Windows")
    current_label = watcher_label(root)
    result = _run_schtasks(["/Query", "/FO", "CSV", "/V"])
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or "could not query scheduled tasks")
    removed = []
    kept = []
    for row in parse_task_rows(result.stdout):
        name = task_name(row)
        if not name or not name.lstrip("\\").startswith(WATCHER_TASK_PREFIX):
            continue
        item = inspect_cleanup_candidate(row, current_label)
        if item["stale"]:
            if not dry_run:
                delete = _run_schtasks(["/Delete", "/TN", name, "/F"])
                if delete.returncode != 0:
                    raise NotifyError(delete.stderr.strip() or f"could not delete scheduled task: {name}")
            removed.append(item)
        else:
            kept.append(item)
    return {"checked": True, "dry_run": dry_run, "removed": removed, "kept": kept}


def parse_task_rows(output):
    return list(csv.DictReader(io.StringIO(output)))


def task_name(row):
    return row.get("TaskName") or row.get("Task Name") or row.get("任务名") or row.get("任务名称")


def task_command(row):
    return row.get("Task To Run") or row.get("TaskToRun") or row.get("要运行的任务") or row.get("执行的任务")


def inspect_cleanup_candidate(row, current_label):
    name = task_name(row) or ""
    label = name.lstrip("\\")
    launcher = extract_launcher_path(task_command(row) or "")
    item = {
        "label": label,
        "task": name,
        "launcher": launcher,
        "current_project": label == current_label,
        "stale": False,
        "reason": None,
    }
    if not launcher:
        item.update({"stale": True, "reason": "launcher path missing"})
    elif not Path(launcher).is_file():
        item.update({"stale": True, "reason": "launcher missing"})
    return item


def extract_launcher_path(command):
    marker = " -File "
    if marker not in command:
        return None
    value = command.split(marker, 1)[1].strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        return value[1:end] if end != -1 else value[1:]
    return value.split()[0] if value else None
