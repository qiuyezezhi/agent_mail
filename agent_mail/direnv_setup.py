"""direnv installation and shell integration helpers."""

import shutil
import subprocess
import sys
from pathlib import Path

from .errors import NotifyError
from .storage import atomic_write_bytes
from .utils import print_json


def default_shell():
    if sys.platform == "darwin":
        return "zsh"
    if sys.platform == "win32":
        return "pwsh"
    raise NotifyError("setup-direnv is only supported on macOS and Windows")


def normalize_shell(shell):
    selected = shell or default_shell()
    if selected not in {"zsh", "pwsh"}:
        raise NotifyError(f"unsupported shell for direnv setup: {selected}")
    if selected == "zsh" and sys.platform != "darwin":
        raise NotifyError("zsh direnv setup is only supported on macOS")
    if selected == "pwsh" and sys.platform != "win32":
        raise NotifyError("PowerShell direnv setup is only supported on Windows")
    return selected


def hook_line(shell):
    if shell == "zsh":
        return 'eval "$(direnv hook zsh)"'
    if shell == "pwsh":
        return 'Invoke-Expression "$(direnv hook pwsh)"'
    raise NotifyError(f"unsupported shell for direnv setup: {shell}")


def profile_path(shell):
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "pwsh":
        return home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    raise NotifyError(f"unsupported shell for direnv setup: {shell}")


def find_direnv():
    executable = shutil.which("direnv")
    if executable:
        return executable
    windows_link = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "direnv.exe"
    if sys.platform == "win32" and windows_link.exists():
        return str(windows_link)
    return None


def install_direnv(shell):
    if shell == "zsh":
        brew = shutil.which("brew")
        if brew is None:
            raise NotifyError("direnv not found and Homebrew is unavailable; install Homebrew or install direnv manually")
        command = [brew, "install", "direnv"]
    elif shell == "pwsh":
        winget = shutil.which("winget")
        if winget is None:
            raise NotifyError("direnv not found and winget is unavailable; install direnv manually or install App Installer first")
        command = [
            winget,
            "install",
            "--id",
            "direnv.direnv",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    else:
        raise NotifyError(f"unsupported shell for direnv setup: {shell}")
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or result.stdout.strip() or "direnv installation failed")
    return {"installed": True, "command": command, "stdout": (result.stdout or "").strip() or None}


def ensure_hook(shell):
    path = profile_path(shell)
    line = hook_line(shell)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = ""
    if line in text.splitlines():
        return {"profile": str(path), "hook_present": True, "hook_added": False}
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, f"{prefix}{line}\n".encode("utf-8"))
    return {"profile": str(path), "hook_present": True, "hook_added": True}


def direnv_status(shell=None):
    selected = normalize_shell(shell)
    path = profile_path(selected)
    line = hook_line(selected)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        "shell": selected,
        "supported": True,
        "available": find_direnv() is not None,
        "executable": find_direnv(),
        "profile": str(path),
        "profile_exists": path.exists(),
        "hook_present": line in text.splitlines(),
        "hook_line": line,
    }


def setup_direnv(shell=None):
    selected = normalize_shell(shell)
    status_before = direnv_status(selected)
    install_result = {"installed": False, "command": None, "stdout": None}
    if not status_before["available"]:
        install_result = install_direnv(selected)
    executable = find_direnv()
    hook_result = ensure_hook(selected)
    return {
        "shell": selected,
        "available": executable is not None,
        "executable": executable,
        "installed_now": install_result["installed"],
        "install_command": install_result["command"],
        "install_stdout": install_result["stdout"],
        **hook_result,
        "restart_required": hook_result["hook_added"] or install_result["installed"],
    }


def prompt_setup_direnv(shell=None):
    selected = normalize_shell(shell)
    question = (
        f"direnv is not installed. Install and configure it now for {selected}? [y/N] "
    )
    try:
        answer = input(question)
    except EOFError:
        return None
    answer = answer.strip().lower()
    if answer not in {"y", "yes"}:
        return {
            "shell": selected,
            "skipped": True,
            "reason": "user declined automatic direnv setup",
        }
    return setup_direnv(selected)


def command_setup_direnv(args):
    if getattr(args, "status", False):
        print_json(direnv_status(args.shell))
        return
    print_json(setup_direnv(args.shell))
