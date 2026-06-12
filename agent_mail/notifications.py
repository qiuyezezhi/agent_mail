"""Platform system notifications for main-agent delivery."""

import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .errors import NotifyError

MACOS_NOTIFIER_BUNDLE_ID = "dev.dplake.agent-notify.notifier"
MACOS_NOTIFIER_APP_NAME = "agent-notify"
MACOS_NOTIFIER_EXECUTABLE = "agent-notify-notifier"
MACOS_NOTIFIER_ICON = "agent-notify"
MACOS_LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
)

MACOS_NOTIFIER_SWIFT = r'''
import AppKit
import Foundation
import UserNotifications

func argumentValue(_ name: String) -> String {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: name), index + 1 < args.count else {
        return ""
    }
    return args[index + 1]
}

func payloadValue(_ payload: [String: Any], _ name: String, fallback: String) -> String {
    payload[name] as? String ?? fallback
}

func readPayload(_ path: String) -> [String: Any] {
    guard !path.isEmpty else {
        return [:]
    }
    let url = URL(fileURLWithPath: path)
    guard let data = try? Data(contentsOf: url) else {
        return [:]
    }
    let object = try? JSONSerialization.jsonObject(with: data)
    return object as? [String: Any] ?? [:]
}

struct MessageDetails {
    let messageID: String
    let subject: String
    let sender: String
    let recipient: String
    let body: String

    var title: String {
        "agent-notify: \(subject)"
    }

    var summary: String {
        "From \(sender) to \(recipient)"
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate, NSWindowDelegate {
    private let details: MessageDetails
    private var panel: NSPanel?
    private var quitTimer: Timer?

    init(details: MessageDetails) {
        self.details = details
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        UNUserNotificationCenter.current().delegate = self
        scheduleQuit(after: 300)
        deliverNotification()
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        DispatchQueue.main.async {
            self.showDetailCard()
            completionHandler()
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.terminate(nil)
    }

    private func deliverNotification() {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            if let error = error {
                writeError("notification authorization failed: \(error.localizedDescription)")
                exit(2)
            }
            if !granted {
                writeError("notification authorization denied")
                exit(3)
            }

            let content = UNMutableNotificationContent()
            content.title = self.details.title
            content.body = self.details.summary
            content.sound = .default

            let request = UNNotificationRequest(identifier: self.details.messageID, content: content, trigger: nil)
            center.add(request) { error in
                if let error = error {
                    writeError("notification delivery failed: \(error.localizedDescription)")
                    exit(4)
                }
            }
        }
    }

    private func showDetailCard() {
        quitTimer?.invalidate()

        if let panel = panel {
            panel.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let card = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 580, height: 400),
            styleMask: [.titled, .closable, .utilityWindow, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        card.title = "agent-notify"
        card.titleVisibility = .hidden
        card.titlebarAppearsTransparent = true
        card.isReleasedWhenClosed = false
        card.hidesOnDeactivate = false
        card.backgroundColor = .clear
        card.isOpaque = false
        card.isMovableByWindowBackground = true
        card.delegate = self
        card.level = .floating
        card.center()

        let content = NSView(frame: card.contentView?.bounds ?? NSRect(x: 0, y: 0, width: 580, height: 400))
        content.translatesAutoresizingMaskIntoConstraints = false
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor.clear.cgColor
        let cardSurface = cardView()

        let accent = accentView()
        let title = label(details.subject, size: 20, weight: .semibold)
        let meta = NSStackView(views: [pill("From", details.sender), pill("To", details.recipient), pill("ID", details.messageID)])
        meta.orientation = .horizontal
        meta.alignment = .centerY
        meta.spacing = 8
        meta.translatesAutoresizingMaskIntoConstraints = false
        let messageLabel = label("Message", size: 11, weight: .medium, color: .secondaryLabelColor)
        let body = bodyView(details.body)

        let stack = NSStackView(views: [accent, title, meta, messageLabel, body])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false

        cardSurface.addSubview(stack)
        content.addSubview(cardSurface)
        card.contentView = content
        NSLayoutConstraint.activate([
            cardSurface.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            cardSurface.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            cardSurface.topAnchor.constraint(equalTo: content.topAnchor),
            cardSurface.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: cardSurface.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: cardSurface.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: cardSurface.topAnchor, constant: 44),
            stack.bottomAnchor.constraint(equalTo: cardSurface.bottomAnchor, constant: -22),
            accent.widthAnchor.constraint(equalToConstant: 72),
            accent.heightAnchor.constraint(equalToConstant: 4),
            body.widthAnchor.constraint(equalTo: stack.widthAnchor),
            body.heightAnchor.constraint(greaterThanOrEqualToConstant: 196),
        ])

        panel = card
        card.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func scheduleQuit(after seconds: TimeInterval) {
        quitTimer?.invalidate()
        quitTimer = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { _ in
            NSApp.terminate(nil)
        }
    }
}

final class CardVisualEffectView: NSVisualEffectView {
    override var allowsVibrancy: Bool {
        return true
    }
}

func label(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor = .labelColor) -> NSTextField {
    let view = NSTextField(labelWithString: text)
    view.font = .systemFont(ofSize: size, weight: weight)
    view.textColor = color
    view.lineBreakMode = .byWordWrapping
    view.maximumNumberOfLines = 0
    view.translatesAutoresizingMaskIntoConstraints = false
    return view
}

func cardView() -> NSVisualEffectView {
    let view = CardVisualEffectView()
    view.material = .popover
    view.blendingMode = .withinWindow
    view.state = .active
    view.isEmphasized = true
    view.appearance = NSAppearance(named: .aqua)
    view.translatesAutoresizingMaskIntoConstraints = false
    view.wantsLayer = true
    view.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.34).cgColor
    view.layer?.borderWidth = 1
    view.layer?.cornerRadius = 18
    view.layer?.shadowColor = NSColor.black.withAlphaComponent(0.18).cgColor
    view.layer?.shadowOpacity = 1
    view.layer?.shadowRadius = 18
    view.layer?.shadowOffset = CGSize(width: 0, height: -6)
    return view
}

func accentView() -> NSView {
    let view = NSView()
    view.translatesAutoresizingMaskIntoConstraints = false
    view.wantsLayer = true
    view.layer?.backgroundColor = NSColor.systemTeal.withAlphaComponent(0.82).cgColor
    view.layer?.cornerRadius = 2
    return view
}

func pill(_ labelText: String, _ value: String) -> NSView {
    let labelView = label(labelText.uppercased(), size: 10, weight: .semibold, color: .secondaryLabelColor)
    let valueView = label(value, size: 12, weight: .medium, color: .labelColor)
    let stack = NSStackView(views: [labelView, valueView])
    stack.orientation = .horizontal
    stack.alignment = .centerY
    stack.spacing = 6
    stack.edgeInsets = NSEdgeInsets(top: 5, left: 9, bottom: 5, right: 9)
    stack.translatesAutoresizingMaskIntoConstraints = false
    stack.wantsLayer = true
    stack.layer?.backgroundColor = NSColor.controlBackgroundColor.withAlphaComponent(0.48).cgColor
    stack.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.38).cgColor
    stack.layer?.borderWidth = 1
    stack.layer?.cornerRadius = 9
    return stack
}

func bodyView(_ text: String) -> NSScrollView {
    let body = NSTextField(wrappingLabelWithString: text.isEmpty ? "(empty body)" : text)
    body.font = .systemFont(ofSize: 14)
    body.textColor = .labelColor
    body.lineBreakMode = .byWordWrapping
    body.translatesAutoresizingMaskIntoConstraints = false
    let scroll = NSScrollView()
    scroll.borderType = .noBorder
    scroll.hasVerticalScroller = true
    scroll.documentView = body
    scroll.drawsBackground = false
    scroll.wantsLayer = true
    scroll.layer?.backgroundColor = NSColor.controlBackgroundColor.withAlphaComponent(0.42).cgColor
    scroll.layer?.borderColor = NSColor.systemTeal.withAlphaComponent(0.26).cgColor
    scroll.layer?.borderWidth = 1
    scroll.layer?.cornerRadius = 14
    scroll.translatesAutoresizingMaskIntoConstraints = false
    NSLayoutConstraint.activate([
        body.leadingAnchor.constraint(equalTo: scroll.contentView.leadingAnchor, constant: 16),
        body.trailingAnchor.constraint(equalTo: scroll.contentView.trailingAnchor, constant: -16),
        body.topAnchor.constraint(equalTo: scroll.contentView.topAnchor, constant: 16),
        body.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor, constant: -32),
    ])
    return scroll
}

func writeError(_ message: String) {
    FileHandle.standardError.write(Data("\(message)\n".utf8))
}

let payloadPath = argumentValue("--payload-file")
let payload = readPayload(payloadPath)
if !payloadPath.isEmpty {
    try? FileManager.default.removeItem(atPath: payloadPath)
}
let details = MessageDetails(
    messageID: payloadValue(payload, "message_id", fallback: argumentValue("--message-id")),
    subject: payloadValue(payload, "subject", fallback: argumentValue("--subject")),
    sender: payloadValue(payload, "from", fallback: argumentValue("--from")),
    recipient: payloadValue(payload, "to", fallback: argumentValue("--to")),
    body: payloadValue(payload, "body", fallback: argumentValue("--body"))
)
let delegate = AppDelegate(details: details)
let app = NSApplication.shared
app.delegate = delegate
app.run()
'''


def _escape_applescript(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(value):
    return str(value).replace("'", "''")


def macos_notifier_app_dir():
    return Path.home() / "Library" / "Application Support" / "agent-notify" / "notifier" / "agent-notify.app"


def macos_notifier_executable(app_dir):
    return Path(app_dir) / "Contents" / "MacOS" / MACOS_NOTIFIER_EXECUTABLE


def macos_notifier_payload_dir(app_dir=None):
    selected_app_dir = Path(app_dir) if app_dir else macos_notifier_app_dir()
    return selected_app_dir.parent / "payloads"


def macos_icon_source():
    return Path(__file__).resolve().parents[1] / "assets" / "agent-notify-icon.png"


def write_macos_notification_payload(message, payload_dir=None):
    selected_payload_dir = Path(payload_dir) if payload_dir else macos_notifier_payload_dir()
    selected_payload_dir.mkdir(parents=True, exist_ok=True)
    selected_payload_dir.chmod(0o700)
    payload = {
        "message_id": str(message["id"]),
        "subject": str(message["subject"]),
        "from": str(message["from"]),
        "to": str(message["to"]),
        "body": str(message.get("body", "")),
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="message-",
        suffix=".json",
        dir=selected_payload_dir,
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
        path = Path(handle.name)
    path.chmod(0o600)
    return path


def write_macos_notifier_bundle(app_dir, executable):
    app_dir = Path(app_dir)
    contents = app_dir / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": Path(executable).name,
        "CFBundleIconFile": MACOS_NOTIFIER_ICON,
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


def install_macos_notifier_icon(app_dir, source_icon=None):
    source = Path(source_icon) if source_icon else macos_icon_source()
    if not source.exists():
        return {"installed": False, "reason": "source icon not found", "source": str(source)}
    sips = shutil.which("sips")
    iconutil = shutil.which("iconutil")
    if sips is None or iconutil is None:
        return {"installed": False, "reason": "icon tools not found", "source": str(source)}

    resources = Path(app_dir) / "Contents" / "Resources"
    icns = resources / f"{MACOS_NOTIFIER_ICON}.icns"
    resources.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{MACOS_NOTIFIER_ICON}.", suffix=".iconset", dir=resources) as iconset_name:
        iconset = Path(iconset_name)
        sizes = [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png"),
        ]
        for pixels, name in sizes:
            result = subprocess.run(
                [sips, "-z", str(pixels), str(pixels), str(source), "--out", str(iconset / name)],
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                return {
                    "installed": False,
                    "reason": "sips failed",
                    "source": str(source),
                    "stderr": result.stderr.strip() or None,
                    "stdout": result.stdout.strip() or None,
                }
        temp_icns = resources / f"{MACOS_NOTIFIER_ICON}.{Path(iconset_name).name}.icns"
        result = subprocess.run([iconutil, "-c", "icns", str(iconset), "-o", str(temp_icns)], text=True, capture_output=True)
        if result.returncode != 0:
            return {
                "installed": False,
                "reason": "iconutil failed",
                "source": str(source),
                "stderr": result.stderr.strip() or None,
                "stdout": result.stdout.strip() or None,
            }
        temp_icns.replace(icns)
    return {"installed": True, "source": str(source), "icns": str(icns)}


def find_lsregister():
    path = Path(MACOS_LSREGISTER)
    if path.exists():
        return str(path)
    return shutil.which("lsregister")


def register_macos_notifier_app(app_dir):
    Path(app_dir).touch()
    lsregister = find_lsregister()
    if lsregister is None:
        return {"registered": False, "reason": "lsregister not found"}
    result = subprocess.run([lsregister, "-f", str(app_dir)], text=True, capture_output=True)
    if result.returncode != 0:
        return {
            "registered": False,
            "reason": "lsregister failed",
            "stderr": result.stderr.strip() or None,
            "stdout": result.stdout.strip() or None,
        }
    return {"registered": True}


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
    icon = install_macos_notifier_icon(selected_app_dir)
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
    registered = register_macos_notifier_app(selected_app_dir)
    return {
        "installed": True,
        "app": str(selected_app_dir),
        "executable": str(executable),
        "icon": icon,
        "registered": registered,
    }


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
        payload_file = write_macos_notification_payload(message, macos_notifier_payload_dir(notifier_app))
        return [
            "open",
            "-gj",
            "-n",
            str(notifier_app),
            "--args",
            "--payload-file",
            str(payload_file),
        ]
    script = (
        f'display notification "{_escape_applescript(body)}" '
        f'with title "{_escape_applescript(title)}"'
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
