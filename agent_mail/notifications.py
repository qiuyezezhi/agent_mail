"""Platform system notifications for main-agent delivery."""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import NotifyError

MACOS_NOTIFIER_BUNDLE_ID = "dev.dplake.agent-notify.notifier"
MACOS_NOTIFIER_APP_NAME = "agent-notify"
MACOS_NOTIFIER_EXECUTABLE = "agent-notify-notifier"

MACOS_NOTIFIER_SWIFT = r'''
import Foundation
import UserNotifications

func argumentValue(_ name: String) -> String {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: name), index + 1 < args.count else {
        return ""
    }
    return args[index + 1]
}

let title = argumentValue("--title")
let subtitle = argumentValue("--subtitle")
let body = argumentValue("--body")
let center = UNUserNotificationCenter.current()
let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 0

center.requestAuthorization(options: [.alert, .sound]) { granted, error in
    if let error = error {
        FileHandle.standardError.write(Data("notification authorization failed: \(error.localizedDescription)\n".utf8))
        exitCode = 2
        semaphore.signal()
        return
    }
    if !granted {
        FileHandle.standardError.write(Data("notification authorization denied\n".utf8))
        exitCode = 3
        semaphore.signal()
        return
    }

    let content = UNMutableNotificationContent()
    content.title = title
    content.subtitle = subtitle
    content.body = body
    content.sound = .default

    let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
    center.add(request) { error in
        if let error = error {
            FileHandle.standardError.write(Data("notification delivery failed: \(error.localizedDescription)\n".utf8))
            exitCode = 4
        }
        semaphore.signal()
    }
}

if semaphore.wait(timeout: .now() + 10) == .timedOut {
    FileHandle.standardError.write(Data("notification delivery timed out\n".utf8))
    exitCode = 5
}

RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.5))
exit(exitCode)
'''


def _escape_applescript(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(value):
    return str(value).replace("'", "''")


def macos_notifier_app_dir():
    return Path.home() / "Library" / "Application Support" / "agent-notify" / "notifier" / "agent-notify.app"


def macos_notifier_executable(app_dir):
    return Path(app_dir) / "Contents" / "MacOS" / MACOS_NOTIFIER_EXECUTABLE


def write_macos_notifier_bundle(app_dir, executable):
    app_dir = Path(app_dir)
    contents = app_dir / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": Path(executable).name,
        "CFBundleIdentifier": MACOS_NOTIFIER_BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": MACOS_NOTIFIER_APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    return contents / "Info.plist"


def install_macos_notifier_app(app_dir=None):
    if sys.platform != "darwin":
        return {"installed": False, "reason": "unsupported platform"}

    selected_app_dir = Path(app_dir) if app_dir else macos_notifier_app_dir()
    executable = macos_notifier_executable(selected_app_dir)
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        return {"installed": False, "reason": "swiftc not found", "app": str(selected_app_dir)}
    codesign = shutil.which("codesign")
    if codesign is None:
        return {"installed": False, "reason": "codesign not found", "app": str(selected_app_dir)}

    source = selected_app_dir / "Contents" / "Resources" / "AgentNotifyNotifier.swift"
    source.parent.mkdir(parents=True, exist_ok=True)
    executable.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(MACOS_NOTIFIER_SWIFT.lstrip(), encoding="utf-8")
    result = subprocess.run(
        [swiftc, str(source), "-o", str(executable)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return {
            "installed": False,
            "reason": "swiftc failed",
            "app": str(selected_app_dir),
            "stderr": result.stderr.strip() or None,
            "stdout": result.stdout.strip() or None,
        }
    executable.chmod(0o755)
    write_macos_notifier_bundle(selected_app_dir, executable)
    signed = subprocess.run(
        [codesign, "--force", "--deep", "--sign", "-", str(selected_app_dir)],
        text=True,
        capture_output=True,
    )
    if signed.returncode != 0:
        return {
            "installed": False,
            "reason": "codesign failed",
            "app": str(selected_app_dir),
            "stderr": signed.stderr.strip() or None,
            "stdout": signed.stdout.strip() or None,
        }
    return {"installed": True, "app": str(selected_app_dir), "executable": str(executable)}


def ensure_macos_notifier_app():
    app_dir = macos_notifier_app_dir()
    executable = macos_notifier_executable(app_dir)
    info_plist = app_dir / "Contents" / "Info.plist"
    if executable.exists() and info_plist.exists():
        return app_dir
    status = install_macos_notifier_app(app_dir)
    if status.get("installed"):
        return app_dir
    return None


def build_macos_notification_command(message, notifier_app=None):
    title = f"agent-notify: {message['subject']}"
    body = f"From {message['from']} to {message['to']}"
    if notifier_app is not None:
        return [
            "open",
            "-W",
            "-gj",
            "-n",
            str(notifier_app),
            "--args",
            "--title",
            title,
            "--subtitle",
            str(message["id"]),
            "--body",
            body,
        ]
    script = (
        f'display notification "{_escape_applescript(body)}" '
        f'with title "{_escape_applescript(title)}" '
        f'subtitle "{_escape_applescript(message["id"])}"'
    )
    return ["osascript", "-e", script]


def build_notification_command(platform, message, macos_notifier_app=None):
    title = f"agent-notify: {message['subject']}"
    body = f"From {message['from']} to {message['to']}"
    if platform == "darwin":
        return build_macos_notification_command(message, notifier_app=macos_notifier_app)
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
    macos_notifier_app = ensure_macos_notifier_app() if selected == "darwin" else None
    command = build_notification_command(selected, message, macos_notifier_app=macos_notifier_app)
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or result.stdout.strip() or "notification delivery failed")
    output = {"platform": "macos" if selected == "darwin" else "windows"}
    if selected == "darwin":
        output["notifier"] = "helper-app" if macos_notifier_app else "osascript"
    return output
