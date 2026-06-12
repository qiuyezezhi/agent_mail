"""Platform system notifications for main-agent delivery."""

import subprocess
import sys

from .errors import NotifyError


def _escape_applescript(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(value):
    return str(value).replace("'", "''")


def build_notification_command(platform, message):
    title = f"agent-notify: {message['subject']}"
    body = f"From {message['from']} to {message['to']}"
    if platform == "darwin":
        script = (
            f'display notification "{_escape_applescript(body)}" '
            f'with title "{_escape_applescript(title)}" '
            f'subtitle "{_escape_applescript(message["id"])}"'
        )
        return ["osascript", "-e", script]
    if platform == "win32":
        script = (
            f"$title = '{_escape_powershell(title)}'\n"
            f"$body = '{_escape_powershell(body)}'\n"
            "Add-Type -AssemblyName System.Windows.Forms\n"
            "Add-Type -AssemblyName System.Drawing\n"
            "$notify = New-Object System.Windows.Forms.NotifyIcon\n"
            "$notify.Icon = [System.Drawing.SystemIcons]::Information\n"
            "$notify.Visible = $true\n"
            "$notify.BalloonTipTitle = $title\n"
            "$notify.BalloonTipText = $body\n"
            "$notify.ShowBalloonTip(5000)\n"
            "Start-Sleep -Seconds 6\n"
            "$notify.Dispose()\n"
        )
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", script]
    raise NotifyError("system notifications are only supported on macOS and Windows")


def notify_main_agent(message, platform=None):
    selected = platform or sys.platform
    command = build_notification_command(selected, message)
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or result.stdout.strip() or "notification delivery failed")
    return {"platform": "macos" if selected == "darwin" else "windows"}
