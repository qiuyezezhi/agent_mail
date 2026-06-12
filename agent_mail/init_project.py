"""Project initialization helpers."""

import shutil
import subprocess
import sys

from .constants import AGENT_RULES_TEXT
from .direnv_setup import find_direnv, prompt_setup_direnv, setup_direnv
from .errors import NotifyError
from .paths import repo_notify_root
from .registry import infer_agent_type, load_agent_records, load_agents, save_agent_records
from .storage import atomic_write_bytes, ensure_dirs, write_lock
from .utils import parse_agent_names, print_json
from .watch_service import install_watcher


def ensure_gitignore_entry(project_root, entry=".agent-notify/"):
    path = project_root / ".gitignore"
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = ""
    lines = text.splitlines()
    if entry in lines:
        return False
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    atomic_write_bytes(path, f"{prefix}{entry}\n".encode("utf-8"))
    return True


def ensure_project_envrc(project_root, line="PATH_add bin"):
    path = project_root / ".envrc"
    if path.exists():
        return False
    atomic_write_bytes(path, f"{line}\n".encode("utf-8"))
    return True


def ensure_project_entrypoint(project_root):
    bin_dir = project_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    scripts = {
        "agent-notify": (
            "#!/usr/bin/env python3\n"
            '"""Repository-local entry point for the bundled agent-notify tool."""\n\n'
            "import runpy\n"
            "import sys\n"
            "from pathlib import Path\n\n\n"
            'if __name__ == "__main__":\n'
            '    project_root = Path(__file__).resolve().parents[1]\n'
            '    sys.path.insert(0, str(project_root))\n'
            '    target = project_root / "cli.py"\n'
            '    runpy.run_path(str(target), run_name="__main__")\n'
        ),
        "agent-notify.cmd": (
            "@echo off\r\n"
            "setlocal\r\n"
            'set "SCRIPT_DIR=%~dp0"\r\n'
            'set "CLI=%SCRIPT_DIR%..\\cli.py"\r\n'
            'py -3 "%CLI%" %*\r\n'
            "if errorlevel 9009 python \"%CLI%\" %*\r\n"
        ),
        "agent-notify.ps1": (
            "$ErrorActionPreference = 'Stop'\n"
            "$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
            '$cli = Join-Path $scriptDir "..\\cli.py"\n'
            "if (Get-Command py -ErrorAction SilentlyContinue) {\n"
            "    & py -3 $cli @Args\n"
            "    exit $LASTEXITCODE\n"
            "}\n"
            "& python $cli @Args\n"
            "exit $LASTEXITCODE\n"
        ),
    }
    updated = False
    for name, content in scripts.items():
        path = bin_dir / name
        if path.exists():
            continue
        atomic_write_bytes(path, content.encode("utf-8"))
        if "." not in name:
            path.chmod(0o755)
        updated = True
    return updated


def maybe_allow_direnv(project_root, envrc_updated, executable=None):
    if not envrc_updated:
        return {
            "available": (executable or find_direnv()) is not None,
            "allowed": False,
            "reason": "existing .envrc left unchanged",
        }
    executable = executable or find_direnv()
    if executable is None:
        return {
            "available": False,
            "allowed": False,
            "reason": "direnv executable not found",
        }
    result = subprocess.run(
        [executable, "allow", str(project_root)],
        text=True,
        capture_output=True,
    )
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return {
            "available": True,
            "allowed": True,
            "reason": "generated .envrc allowed",
            "stdout": output or None,
        }
    return {
        "available": True,
        "allowed": False,
        "reason": "direnv allow failed",
        "stdout": (result.stdout or "").strip() or None,
        "stderr": (result.stderr or "").strip() or None,
        "returncode": result.returncode,
    }

def parse_agent_specs(value):
    specs = []
    for item in parse_agent_names(value):
        if ":" in item:
            name, agent_type_value = item.split(":", 1)
            name = name.strip()
            agent_type_value = agent_type_value.strip()
            if not name or not agent_type_value:
                raise NotifyError(f"invalid agent spec: {item}")
            specs.append({"name": name, "type": infer_agent_type(name, agent_type_value)})
        else:
            specs.append({"name": item, "type": infer_agent_type(item, None)})
    return specs

def register_missing_agents(root, agent_specs):
    with write_lock(root):
        ensure_dirs(root)
        existing = load_agent_records(root)
        existing_names = {record["name"] for record in existing}
        existing_has_main = any(record.get("main") for record in existing)
        missing_records = []
        for index, record in enumerate(agent_specs):
            if record["name"] in existing_names:
                continue
            missing_records.append(
                {
                    "name": record["name"],
                    "type": record["type"],
                    "main": (not existing_has_main and not missing_records and index == 0),
                }
            )
        missing = [record["name"] for record in missing_records]
        if missing:
            save_agent_records(root, [*existing, *missing_records])
    return sorted(missing)

def command_init(args):
    root = repo_notify_root()
    project_root = root.parent
    ensure_dirs(root)
    agent_specs = parse_agent_specs(args.agents) if args.agents else []
    registered = register_missing_agents(root, agent_specs)
    gitignore_updated = False if args.no_gitignore else ensure_gitignore_entry(project_root)
    envrc_updated = ensure_project_envrc(project_root)
    entrypoint_updated = ensure_project_entrypoint(project_root)
    direnv_setup = None
    direnv_executable = find_direnv()
    if args.setup_direnv:
        direnv_setup = setup_direnv()
        direnv_executable = direnv_setup["executable"]
    elif direnv_executable is None and sys.stdin.isatty() and sys.stdout.isatty():
        direnv_setup = prompt_setup_direnv()
        if direnv_setup and not direnv_setup.get("skipped"):
            direnv_executable = direnv_setup["executable"]
    direnv_status = maybe_allow_direnv(project_root, envrc_updated, executable=direnv_executable)
    watcher = {"installed": False}
    if args.install_watcher:
        watcher = install_watcher(root, args.watch_agents or args.agents, args.interval, args.timeout)
    output = {
        "root": str(root.resolve()),
        "gitignore": None if args.no_gitignore else str((project_root / ".gitignore").resolve()),
        "gitignore_updated": gitignore_updated,
        "envrc": str((project_root / ".envrc").resolve()),
        "envrc_updated": envrc_updated,
        "entrypoint": str((project_root / "bin" / "agent-notify").resolve()),
        "entrypoints": {
            "posix": str((project_root / "bin" / "agent-notify").resolve()),
            "cmd": str((project_root / "bin" / "agent-notify.cmd").resolve()),
            "powershell": str((project_root / "bin" / "agent-notify.ps1").resolve()),
        },
        "entrypoint_updated": entrypoint_updated,
        "direnv": direnv_status,
        "direnv_setup": direnv_setup,
        "agents": load_agents(root),
        "agent_details": load_agent_records(root),
        "registered_agents": registered,
        "watcher": watcher,
        "next_steps": [
            "agent-notify setup-direnv",
            "agent-notify register <agent-name> --type <codex|claude|reasonix> --main",
            "agent-notify register <agent-name> --type <codex|claude|reasonix>",
            "agent-notify lint",
            "agent-notify inbox --agent <agent>",
            "agent-notify watch install --agents <agent-name>,<agent-name>",
        ],
    }
    if args.print_agent_rules:
        output["rules"] = AGENT_RULES_TEXT
    print_json(output)
