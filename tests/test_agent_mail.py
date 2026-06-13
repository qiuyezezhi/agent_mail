import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI_SCRIPT = ROOT / "cli.py"
CLI_SOURCE = ROOT / "agent_mail" / "storage.py"


class AgentNotifyCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.run_git(Path(self.tmp.name), "init", "repo")
        self.run_git(self.repo, "config", "user.email", "test@example.com")
        self.run_git(self.repo, "config", "user.name", "Test User")
        (self.repo / "README.md").write_text("test repo\n", encoding="utf-8")
        self.run_git(self.repo, "add", "README.md")
        self.run_git(self.repo, "commit", "-m", "init")
        default_bin = Path(self.tmp.name) / "default-bin"
        default_bin.mkdir()
        self.write_fake_claude(
            default_bin,
            "#!/usr/bin/env python3\n"
            "raise SystemExit(19)\n",
        )
        self.default_env = os.environ.copy()
        self.default_env["PATH"] = f"{default_bin}{os.pathsep}{self.default_env['PATH']}"

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, cwd, *args):
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )

    def cli(self, *args, cwd=None, stdin=None, ok=True, env=None):
        effective_env = self.default_env.copy()
        if env is not None:
            effective_env.update(env)
        result = subprocess.run(
            [sys.executable, str(CLI_SCRIPT), *args],
            cwd=cwd or self.repo,
            input=stdin,
            text=True,
            capture_output=True,
            env=effective_env,
        )
        if ok and result.returncode != 0:
            self.fail(f"command failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}")
        if not ok and result.returncode == 0:
            self.fail(f"command unexpectedly passed: {args}\nstdout={result.stdout}")
        return result

    def parse_json(self, result):
        return json.loads(result.stdout)

    def register_default_agents(self):
        self.cli("register", "codex", "--type", "codex", "--main")
        self.cli("register", "reasonix", "--type", "reasonix")

    def send(self, subject="Subject", body="Body", source_session_id=None):
        args = [
            "send",
            "--from",
            "codex",
            "--to",
            "reasonix",
            "--subject",
            subject,
            "--body",
            body,
        ]
        if source_session_id is not None:
            args.extend(["--source-session-id", source_session_id])
        result = self.cli(*args)
        return self.parse_json(result)

    def test_help_lists_tool_purpose_interfaces_and_command_parameters(self):
        overview = self.parse_json(self.cli("help"))

        self.assertIn("purpose", overview)
        self.assertIn("interfaces", overview)
        self.assertIn("init", overview["interfaces"])
        self.assertIn("send", overview["interfaces"])
        self.assertIn("update", overview["interfaces"])
        self.assertIn("watch run", overview["interfaces"])
        self.assertIn("watch cleanup", overview["interfaces"])
        self.assertIn("docs/cli-reference.md", overview["docs"]["cli_reference"])

        send_help = self.parse_json(self.cli("help", "send"))
        self.assertEqual(send_help["command"], "send")
        self.assertEqual(send_help["purpose"], "Queue a notification for a registered agent.")
        self.assertEqual(send_help["parameters"]["--from"], "Required sender agent name.")
        self.assertEqual(send_help["parameters"]["--to"], "Required recipient agent name.")
        self.assertIn("--source-session-id", send_help["parameters"])

    def test_argparse_help_includes_command_and_parameter_descriptions(self):
        top = self.cli("--help")
        self.assertIn("register", top.stdout)
        self.assertIn("Register an agent inbox name", top.stdout)
        self.assertIn("watch", top.stdout)
        self.assertIn("Run or manage the background watcher", top.stdout)

        register = self.cli("register", "--help")
        self.assertIn("Register an agent inbox name", register.stdout)
        self.assertIn("Required inbox address", register.stdout)
        self.assertIn("Mark this agent as the single global main-agent", register.stdout)

    def test_update_refreshes_entrypoints_without_watcher(self):
        shutil.copytree(ROOT / "agent_mail", self.repo / "agent_mail")
        shutil.copy2(ROOT / "cli.py", self.repo / "cli.py")
        self.cli("init")
        entrypoint = self.repo / "bin" / "agent-notify"
        entrypoint.write_text("#!/usr/bin/env python3\nprint('old')\n", encoding="utf-8")

        output = self.parse_json(self.cli("update", "--no-watch", "--no-direnv"))

        self.assertTrue(output["entrypoint_updated"])
        self.assertEqual(output["watcher"]["reason"], "skipped")
        self.assertIn("cli.py", entrypoint.read_text(encoding="utf-8"))
        self.assertNotIn("print('old')", entrypoint.read_text(encoding="utf-8"))

    def test_update_restarts_installed_launchd_watcher_clearing_legacy_agent_filter(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import launchd, update_project, watch_service

        root = self.repo / ".agent-notify"
        root.mkdir()
        home = Path(self.tmp.name) / "home"
        calls = []

        def fake_run(args, text=True, capture_output=True):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            mock.patch("agent_mail.launchd.sys.platform", "darwin"),
            mock.patch("agent_mail.watch_service.sys.platform", "darwin"),
            mock.patch("agent_mail.launchd.Path.home", return_value=home),
            mock.patch("agent_mail.launchd.subprocess.run", side_effect=fake_run),
        ):
            launchd.install_watcher(root, "claude,reasonix", 7, 1800)
            executable = launchd.watcher_executable_path(root)
            self.assertTrue(executable.is_symlink())
            output = update_project.update_watcher(
                root,
                SimpleNamespace(no_watch=False, watch_agents=None, interval=None, timeout=None),
            )

        self.assertTrue(output["updated"])
        self.assertEqual(output["agents"], "")
        self.assertEqual(output["interval"], 7.0)
        self.assertEqual(output["timeout"], 1800.0)
        self.assertTrue(executable.is_symlink())
        self.assertEqual(Path(output["installed"]["executable"]), executable)
        with Path(output["installed"]["plist"]).open("rb") as fh:
            plist = plistlib.load(fh)
        self.assertNotIn("--agents", plist["ProgramArguments"])
        self.assertGreaterEqual(
            sum(1 for call in calls if call[:1] == ["launchctl"] and "load" in call),
            2,
        )

    def test_update_does_not_install_watcher_when_not_already_installed(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import launchd, update_project, watch_service

        root = self.repo / ".agent-notify"
        root.mkdir()
        home = Path(self.tmp.name) / "home"
        calls = []

        def fake_run(args, text=True, capture_output=True):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1, "", "not loaded")

        with (
            mock.patch("agent_mail.launchd.sys.platform", "darwin"),
            mock.patch("agent_mail.watch_service.sys.platform", "darwin"),
            mock.patch("agent_mail.launchd.Path.home", return_value=home),
            mock.patch("agent_mail.launchd.subprocess.run", side_effect=fake_run),
        ):
            output = update_project.update_watcher(
                root,
                SimpleNamespace(no_watch=False, watch_agents=None, interval=None, timeout=None),
            )
            plist_path = launchd.watcher_plist_path(root)

        self.assertFalse(output["updated"])
        self.assertEqual(output["reason"], "watcher not installed")
        self.assertFalse(plist_path.exists())
        self.assertNotIn("load", [item for call in calls for item in call])

    def write_claude_session(self, home, session_id, content="{}\n", mtime=1):
        project_key = str(self.repo.resolve()).replace(os.sep, "-")
        sessions = home / ".claude" / "projects" / project_key
        sessions.mkdir(parents=True, exist_ok=True)
        session = sessions / f"{session_id}.jsonl"
        session.write_text(content, encoding="utf-8")
        os.utime(session, (mtime, mtime))
        return session

    def write_claude_history(self, home, entries):
        claude_home = home / ".claude"
        claude_home.mkdir(parents=True, exist_ok=True)
        history = claude_home / "history.jsonl"
        history.write_text(
            "".join(json.dumps(entry) + "\n" for entry in entries),
            encoding="utf-8",
        )
        return history

    def write_fake_claude(self, bin_dir, script):
        fake_claude = bin_dir / "claude"
        fake_claude.write_text(script, encoding="utf-8")
        fake_claude.chmod(0o755)
        return fake_claude

    def write_fake_codex(self, bin_dir, script):
        fake_codex = bin_dir / "codex"
        fake_codex.write_text(script, encoding="utf-8")
        fake_codex.chmod(0o755)
        return fake_codex

    def write_codex_session_index(self, home, entries):
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        session_index = codex_home / "session_index.jsonl"
        session_index.write_text(
            "".join(json.dumps(entry) + "\n" for entry in entries),
            encoding="utf-8",
        )
        return session_index

    def write_codex_rollout(self, home, session_id, cwd, mtime=1, date_prefix="2026-06-11"):
        rollout_dir = home / ".codex" / "sessions" / "2026" / "06" / "11"
        rollout_dir.mkdir(parents=True, exist_ok=True)
        rollout = rollout_dir / f"rollout-{date_prefix}T00-00-00-{session_id}.jsonl"
        rollout.write_text(
            json.dumps(
                {
                    "timestamp": f"{date_prefix}T00:00:00.000Z",
                    "type": "turn_context",
                    "payload": {
                        "turn_id": f"turn-{session_id[:8]}",
                        "cwd": str(cwd),
                        "current_date": "2026-06-11",
                        "timezone": "Asia/Shanghai",
                    },
                }
            )
            + "\n"
            + json.dumps(
                {
                    "timestamp": f"{date_prefix}T00:00:01.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "done"}],
                        "phase": "final_answer",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.utime(rollout, (mtime, mtime))
        return rollout

    def write_codex_process_manager(self, home, entries):
        process_manager = home / ".codex" / "process_manager"
        process_manager.mkdir(parents=True, exist_ok=True)
        path = process_manager / "chat_processes.json"
        path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return path

    def test_register_with_type_and_reject_unknown_agents(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        self.cli("register", "worker", "--type", "codex")
        agents = self.parse_json(self.cli("agents"))
        self.assertEqual(agents, ["codex-main", "worker"])
        details = self.parse_json(self.cli("agents", "--details"))
        self.assertEqual(
            details,
            [
                {"name": "codex-main", "type": "codex", "main": True},
                {"name": "worker", "type": "codex", "main": False},
            ],
        )

        duplicate = self.cli("register", "worker", "--type", "codex", ok=False)
        self.assertIn("agent already registered", duplicate.stderr)

        missing_type = self.cli("register", "reviewer", ok=False)
        self.assertIn("agent type is required", missing_type.stderr)

        inferred_legacy = self.parse_json(self.cli("register", "claude"))
        self.assertEqual(inferred_legacy, ["claude", "codex-main", "worker"])

        invalid_type = self.cli("register", "bad", "--type", "other", ok=False)
        self.assertIn("unsupported agent type", invalid_type.stderr)

        unknown_sender = self.cli(
            "send",
            "--from",
            "ghost",
            "--to",
            "worker",
            "--subject",
            "x",
            "--body",
            "y",
            ok=False,
        )
        self.assertIn("unregistered agent", unknown_sender.stderr)

    def test_first_registration_requires_main_agent(self):
        result = self.cli("register", "worker", "--type", "codex", ok=False)
        self.assertIn("main-agent", result.stderr)

    def test_register_main_agent_and_show_it_in_details(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        details = self.parse_json(self.cli("agents", "--details"))
        self.assertEqual(details, [{"name": "codex-main", "type": "codex", "main": True}])

    def test_second_main_agent_registration_is_rejected(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        second = self.cli("register", "claude-main", "--type", "claude", "--main", ok=False)
        self.assertIn("main-agent already exists", second.stderr)

    def test_set_main_switches_the_unique_main_agent(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        self.cli("register", "claude-reviewer", "--type", "claude")
        output = self.parse_json(self.cli("set-main", "claude-reviewer"))
        self.assertEqual(output, {"main_agent": "claude-reviewer", "updated": True})
        details = self.parse_json(self.cli("agents", "--details"))
        self.assertEqual(
            details,
            [
                {"name": "claude-reviewer", "type": "claude", "main": True},
                {"name": "codex-main", "type": "codex", "main": False},
            ],
        )

    def test_set_main_rejects_unknown_agent(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        result = self.cli("set-main", "ghost", ok=False)
        self.assertIn("unregistered agent", result.stderr)

    def test_lint_rejects_registry_with_multiple_main_agents(self):
        notify = self.repo / ".agent-notify"
        notify.mkdir()
        (notify / "agents.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "agents": [
                        {"name": "a", "type": "codex", "main": True},
                        {"name": "b", "type": "claude", "main": True},
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = self.cli("lint", ok=False)
        self.assertIn("multiple main-agents", result.stderr)

    def test_lint_rejects_registry_with_missing_main_agent(self):
        notify = self.repo / ".agent-notify"
        notify.mkdir()
        (notify / "agents.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "agents": [
                        {"name": "a", "type": "codex", "main": False},
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = self.cli("lint", ok=False)
        self.assertIn("missing main-agent", result.stderr)

    def test_set_main_migrates_legacy_null_type_records(self):
        notify = self.repo / ".agent-notify"
        notify.mkdir()
        (notify / "agents.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "agents": [
                        {"name": "Reasonix", "type": None, "main": False},
                        {"name": "codex", "type": "codex", "main": False},
                    ],
                }
            ),
            encoding="utf-8",
        )

        output = self.parse_json(self.cli("set-main", "codex"))
        self.assertEqual(output, {"main_agent": "codex", "updated": True})
        details = self.parse_json(self.cli("agents", "--details"))
        self.assertEqual(
            details,
            [
                {"name": "Reasonix", "type": "reasonix", "main": False},
                {"name": "codex", "type": "codex", "main": True},
            ],
        )

    def test_notify_main_agent_uses_macos_helper_app_when_available(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        message = {"id": "123", "from": "worker", "to": "codex-main", "subject": "Review", "body": "Body"}
        notifier_app = self.repo / ".agent-notify" / "notifier" / "agent-notify.app"
        command = notifications.build_macos_notification_command(message, notifier_app=notifier_app)
        self.assertEqual(command[:5], ["open", "-gj", "-n", str(notifier_app), "--args"])
        self.assertNotIn("-W", command)
        self.assertNotIn("--message-id", command)
        self.assertNotIn("123", command)
        self.assertNotIn("--subject", command)
        self.assertNotIn("Review", command)
        self.assertNotIn("--from", command)
        self.assertNotIn("worker", command)
        self.assertNotIn("--to", command)
        self.assertNotIn("codex-main", command)
        self.assertNotIn("--subtitle", command)
        self.assertNotIn("--body", command)
        self.assertNotIn("Body", command)
        self.assertIn("--payload-file", command)
        payload = Path(command[command.index("--payload-file") + 1])
        self.assertTrue(payload.exists())
        self.assertEqual(payload.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            json.loads(payload.read_text(encoding="utf-8")),
            {"message_id": "123", "subject": "Review", "from": "worker", "to": "codex-main", "body": "Body"},
        )

    def test_macos_notifier_helper_handles_click_with_detail_card(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        source = notifications.MACOS_NOTIFIER_SWIFT
        self.assertIn("UNUserNotificationCenterDelegate", source)
        self.assertIn("userNotificationCenter", source)
        self.assertIn("showDetailCard", source)
        self.assertIn("MessageDetails.from(payload:", source)
        self.assertIn("guard let details = details else", source)
        self.assertIn("content.userInfo", source)
        self.assertIn("response.notification.request.content.userInfo", source)
        self.assertIn("NSPanel", source)
        self.assertIn("hidesOnDeactivate = false", source)
        self.assertIn(".fullSizeContentView", source)
        self.assertIn("titleVisibility = .hidden", source)
        self.assertIn("titlebarAppearsTransparent = true", source)
        self.assertIn("backgroundColor = .clear", source)
        self.assertIn("isOpaque = false", source)
        self.assertNotIn("Copy read command", source)
        self.assertNotIn("NSPasteboard.general", source)
        self.assertNotIn("NSButton(", source)
        self.assertNotIn("Process()", source)
        self.assertIn("bodyView(details.body)", source)
        self.assertIn("cardView()", source)
        self.assertIn("CardVisualEffectView()", source)
        self.assertIn("material = .popover", source)
        self.assertIn("blendingMode = .withinWindow", source)
        self.assertIn("state = .active", source)
        self.assertIn("final class CardVisualEffectView", source)
        self.assertIn("override var allowsVibrancy: Bool", source)
        self.assertIn("return true", source)
        self.assertIn("appearance = NSAppearance(named: .aqua)", source)
        self.assertIn("cardSurface.addSubview(stack)", source)
        self.assertIn("cardSurface.leadingAnchor.constraint(equalTo: content.leadingAnchor)", source)
        self.assertIn("accentView()", source)
        self.assertIn('pill("From", details.sender)', source)
        self.assertIn('pill("To", details.recipient)', source)
        self.assertIn('pill("ID", details.messageID)', source)
        self.assertIn('label("Message", size: 11', source)
        self.assertIn("NSTextField(wrappingLabelWithString:", source)
        self.assertIn("cornerRadius = 14", source)
        self.assertIn("borderColor", source)
        self.assertNotIn("NSTextView()", source)

    def test_notify_main_agent_falls_back_to_osascript_without_macos_helper_app(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        message = {"id": "123", "from": "worker", "to": "codex-main", "subject": "Review", "body": "Body"}
        command = notifications.build_macos_notification_command(message, notifier_app=None)
        self.assertEqual(command[0], "osascript")
        self.assertIn("display notification", command[2])
        self.assertNotIn("subtitle", command[2])
        self.assertNotIn(message["id"], command[2])

    def test_macos_notifier_app_bundle_is_hidden_background_app(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        app_dir = self.repo / ".agent-notify" / "notifier" / "agent-notify.app"
        executable = app_dir / "Contents" / "MacOS" / "agent-notify-notifier"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        notifications.write_macos_notifier_bundle(app_dir, executable)

        info = plistlib.loads((app_dir / "Contents" / "Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], "dev.dplake.agent-notify.notifier")
        self.assertEqual(info["CFBundleIconFile"], "agent-notify")
        self.assertEqual(info["CFBundleName"], "agent-notify")
        self.assertNotIn("LSBackgroundOnly", info)
        self.assertTrue(info["LSUIElement"])

    def test_install_macos_notifier_app_signs_and_registers_bundle(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        app_dir = self.repo / ".agent-notify" / "notifier" / "agent-notify.app"
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[0] == "/usr/bin/swiftc":
                Path(command[-1]).write_text("#!/bin/sh\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch("agent_mail.notifications.shutil.which") as which, mock.patch(
            "agent_mail.notifications.subprocess.run", side_effect=fake_run
        ), mock.patch("agent_mail.notifications.sys.platform", "darwin"), mock.patch(
            "agent_mail.notifications.find_lsregister", return_value="/usr/bin/lsregister"
        ):
            which.side_effect = lambda name: f"/usr/bin/{name}" if name in {"swiftc", "codesign"} else None
            status = notifications.install_macos_notifier_app(app_dir)

        self.assertTrue(status["installed"])
        self.assertEqual(calls[0][0], "/usr/bin/swiftc")
        self.assertEqual(calls[1][:4], ["/usr/bin/codesign", "--force", "--deep", "--sign"])
        self.assertEqual(calls[1][4], "-")
        self.assertEqual(calls[2], ["/usr/bin/lsregister", "-f", str(app_dir)])

    def test_install_macos_notifier_app_generates_icon_when_tools_available(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        app_dir = self.repo / ".agent-notify" / "notifier" / "agent-notify.app"
        source_icon = self.repo / "icon.png"
        source_icon.write_bytes(b"png")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[0] == "/usr/bin/swiftc":
                Path(command[-1]).write_text("#!/bin/sh\n", encoding="utf-8")
            if command[0] == "/usr/bin/iconutil":
                Path(command[-1]).write_bytes(b"icns")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch("agent_mail.notifications.shutil.which") as which, mock.patch(
            "agent_mail.notifications.subprocess.run", side_effect=fake_run
        ), mock.patch("agent_mail.notifications.sys.platform", "darwin"), mock.patch(
            "agent_mail.notifications.macos_icon_source", return_value=source_icon
        ):
            which.side_effect = lambda name: f"/usr/bin/{name}" if name in {"swiftc", "codesign", "sips", "iconutil"} else None
            status = notifications.install_macos_notifier_app(app_dir)

        self.assertTrue(status["icon"]["installed"])
        self.assertTrue((app_dir / "Contents" / "Resources" / "agent-notify.icns").exists())
        self.assertIn("/usr/bin/iconutil", [command[0] for command in calls])

    def test_notify_main_agent_builds_windows_notification_command(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import notifications

        message = {"id": "123", "from": "worker", "to": "codex-main", "subject": "Review", "body": "Body"}
        command = notifications.build_notification_command("win32", message)
        self.assertIn(command[0].lower(), {"powershell.exe", "pwsh"})

    def test_watch_run_once_notifies_main_agent_without_resume(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        self.cli("send", "--from", "codex-main", "--to", "codex-main", "--subject", "Review", "--body", "Body")

        sys.path.insert(0, str(ROOT))
        from agent_mail import watcher

        with mock.patch("agent_mail.watcher.notify_main_agent", return_value={"platform": "macos"}) as notify:
            output = watcher.watch_once(self.repo / ".agent-notify", ["codex-main"], 1800)

        notify.assert_called_once()
        self.assertEqual(output["notified"][0]["agent"], "codex-main")
        inbox = self.parse_json(self.cli("inbox", "--agent", "codex-main"))
        self.assertEqual(inbox[0]["status"], "unread")

        state = json.loads((self.repo / ".agent-notify" / "watcher-state.json").read_text(encoding="utf-8"))
        self.assertIn(inbox[0]["id"], state["delivered_notifications"])

        repeated = watcher.watch_once(self.repo / ".agent-notify", ["codex-main"], 1800)
        self.assertEqual(repeated["notified"], [])

        next_message = self.parse_json(
            self.cli("send", "--from", "codex-main", "--to", "codex-main", "--subject", "Next", "--body", "Next body")
        )
        next_output = watcher.watch_once(self.repo / ".agent-notify", ["codex-main"], 1800)
        self.assertEqual(next_output["notified"][0]["message_id"], next_message["id"])

        self.cli("handle", "--agent", "codex-main", inbox[0]["id"], "--note", "done")
        state = json.loads((self.repo / ".agent-notify" / "watcher-state.json").read_text(encoding="utf-8"))
        self.assertNotIn(inbox[0]["id"], state["delivered_notifications"])

    def test_watch_default_agent_list_includes_main_agent_for_notifications(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        self.cli("register", "claude-reviewer", "--type", "claude")
        self.cli("register", "reasonix-web", "--type", "reasonix")

        sys.path.insert(0, str(ROOT))
        from agent_mail import watcher

        self.assertEqual(
            watcher.parse_agent_list(None, self.repo / ".agent-notify"),
            ["claude-reviewer", "codex-main", "reasonix-web"],
        )

    def test_watch_run_once_keeps_main_agent_message_unread_on_notification_failure(self):
        self.cli("register", "codex-main", "--type", "codex", "--main")
        message = self.parse_json(
            self.cli("send", "--from", "codex-main", "--to", "codex-main", "--subject", "Review", "--body", "Body")
        )

        sys.path.insert(0, str(ROOT))
        from agent_mail import watcher
        from agent_mail.errors import NotifyError

        with mock.patch("agent_mail.watcher.notify_main_agent", side_effect=NotifyError("notify failed")):
            output = watcher.watch_once(self.repo / ".agent-notify", ["codex-main"], 1800)

        self.assertEqual(output["failed"][0]["message_id"], message["id"])
        inbox = self.parse_json(self.cli("inbox", "--agent", "codex-main"))
        self.assertEqual(inbox[0]["status"], "unread")

    def test_init_creates_queue_and_gitignore_without_registering_agents(self):
        first = self.parse_json(self.cli("init"))
        second = self.parse_json(self.cli("init"))

        self.assertEqual(first["root"], str((self.repo / ".agent-notify").resolve()))
        self.assertTrue(first["gitignore_updated"])
        self.assertFalse(second["gitignore_updated"])
        self.assertEqual(first["registered_agents"], [])
        self.assertEqual(second["registered_agents"], [])
        self.assertEqual(self.parse_json(self.cli("agents")), [])

        gitignore = self.repo / ".gitignore"
        self.assertEqual(gitignore.read_text(encoding="utf-8").splitlines().count(".agent-notify/"), 1)
        self.assertTrue((self.repo / ".agent-notify" / "messages").is_dir())
        self.assertTrue((self.repo / ".agent-notify" / "archive").is_dir())
        self.assertTrue((self.repo / ".agent-notify" / "watcher-locks").is_dir())
        self.assertTrue((self.repo / ".agent-notify" / "logs").is_dir())
        self.assertFalse(first["watcher"]["installed"])
        self.assertEqual((self.repo / ".envrc").read_text(encoding="utf-8").strip(), "PATH_add bin")
        self.assertTrue((self.repo / "bin" / "agent-notify").exists())
        self.assertTrue((self.repo / "bin" / "agent-notify.cmd").exists())
        self.assertTrue((self.repo / "bin" / "agent-notify.ps1").exists())
        self.assertTrue(os.access(self.repo / "bin" / "agent-notify", os.X_OK))
        self.assertTrue(first["envrc_updated"])
        self.assertTrue(first["entrypoint_updated"])
        self.assertFalse(second["envrc_updated"])
        self.assertFalse(second["entrypoint_updated"])
        self.assertTrue(first["direnv"]["available"])
        self.assertTrue(first["direnv"]["allowed"])
        self.assertEqual(first["direnv"]["reason"], "generated .envrc allowed")

    def test_init_preserves_existing_envrc(self):
        envrc = self.repo / ".envrc"
        envrc.write_text("export FOO=bar\n", encoding="utf-8")

        output = self.parse_json(self.cli("init"))

        self.assertEqual(envrc.read_text(encoding="utf-8"), "export FOO=bar\n")
        self.assertFalse(output["envrc_updated"])
        self.assertEqual(output["envrc"], str(envrc.resolve()))
        self.assertTrue(output["entrypoint_updated"])
        self.assertEqual(output["direnv"]["reason"], "existing .envrc left unchanged")

    def test_init_auto_allows_generated_envrc_when_direnv_is_available(self):
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        allow_log = Path(self.tmp.name) / "direnv.jsonl"
        fake_direnv = bin_dir / "direnv"
        fake_direnv.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['DIRENV_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        fake_direnv.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["DIRENV_LOG"] = str(allow_log)

        output = self.parse_json(self.cli("init", env=env))

        self.assertTrue(output["envrc_updated"])
        self.assertTrue(output["direnv"]["available"])
        self.assertTrue(output["direnv"]["allowed"])
        self.assertEqual(output["direnv"]["reason"], "generated .envrc allowed")
        self.assertEqual(
            [json.loads(line) for line in allow_log.read_text(encoding="utf-8").splitlines()],
            [["allow", str(self.repo.resolve())]],
        )

    def test_init_can_register_typed_agents_without_gitignore_and_prints_rules(self):
        output = self.parse_json(
            self.cli("init", "--agents", "alice:codex,bob:reasonix", "--no-gitignore", "--print-agent-rules")
        )

        self.assertEqual(output["registered_agents"], ["alice", "bob"])
        self.assertEqual(
            self.parse_json(self.cli("agents", "--details")),
            [
                {"name": "alice", "type": "codex", "main": True},
                {"name": "bob", "type": "reasonix", "main": False},
            ],
        )
        self.assertFalse(output["gitignore_updated"])
        self.assertFalse((self.repo / ".gitignore").exists())
        self.assertIn("rules", output)
        self.assertIn("agent-notify", output["rules"])
        self.assertIn("`send` only queues", output["rules"])

    def test_setup_direnv_installs_and_hooks_zsh_on_macos(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import direnv_setup

        home = Path(self.tmp.name) / "home"
        commands = []

        def fake_which(name):
            if name == "direnv":
                if commands:
                    return "/opt/homebrew/bin/direnv"
                return None
            if name == "brew":
                return "/opt/homebrew/bin/brew"
            return shutil.which(name)

        def fake_run(args, text=True, capture_output=True):
            commands.append(args)
            return subprocess.CompletedProcess(args, 0, "installed", "")

        with (
            mock.patch("agent_mail.direnv_setup.sys.platform", "darwin"),
            mock.patch("agent_mail.direnv_setup.Path.home", return_value=home),
            mock.patch("agent_mail.direnv_setup.shutil.which", side_effect=fake_which),
            mock.patch("agent_mail.direnv_setup.subprocess.run", side_effect=fake_run),
        ):
            output = direnv_setup.setup_direnv("zsh")
            status = direnv_setup.direnv_status("zsh")

        zshrc = home / ".zshrc"
        self.assertTrue(zshrc.exists())
        self.assertIn('eval "$(direnv hook zsh)"', zshrc.read_text(encoding="utf-8"))
        self.assertTrue(output["installed_now"])
        self.assertTrue(output["hook_added"])
        self.assertEqual(commands[0], ["/opt/homebrew/bin/brew", "install", "direnv"])
        self.assertTrue(status["available"])
        self.assertTrue(status["hook_present"])

    def test_setup_direnv_installs_and_hooks_powershell_on_windows(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import direnv_setup

        home = Path(self.tmp.name) / "home"
        commands = []
        windows_direnv = home / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "direnv.exe"

        def fake_which(name):
            if name == "direnv":
                return None
            if name == "winget":
                return "C:\\Windows\\System32\\winget.exe"
            return shutil.which(name)

        def fake_run(args, text=True, capture_output=True):
            commands.append(args)
            windows_direnv.parent.mkdir(parents=True, exist_ok=True)
            windows_direnv.write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "installed", "")

        with (
            mock.patch("agent_mail.direnv_setup.sys.platform", "win32"),
            mock.patch("agent_mail.direnv_setup.Path.home", return_value=home),
            mock.patch("agent_mail.direnv_setup.shutil.which", side_effect=fake_which),
            mock.patch("agent_mail.direnv_setup.subprocess.run", side_effect=fake_run),
        ):
            output = direnv_setup.setup_direnv("pwsh")
            status = direnv_setup.direnv_status("pwsh")

        profile = home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
        self.assertTrue(profile.exists())
        self.assertIn('Invoke-Expression "$(direnv hook pwsh)"', profile.read_text(encoding="utf-8"))
        self.assertTrue(output["installed_now"])
        self.assertTrue(output["hook_added"])
        self.assertEqual(
            commands[0],
            [
                "C:\\Windows\\System32\\winget.exe",
                "install",
                "--id",
                "direnv.direnv",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
        )
        self.assertTrue(status["available"])
        self.assertTrue(status["hook_present"])

    def test_init_setup_direnv_runs_before_allow(self):
        shutil.copytree(ROOT / "agent_mail", self.repo / "agent_mail")
        shutil.copy2(ROOT / "cli.py", self.repo / "cli.py")
        home = Path(self.tmp.name) / "home"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        allow_log = Path(self.tmp.name) / "direnv.jsonl"
        fake_direnv = bin_dir / "direnv"
        fake_direnv.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['DIRENV_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        fake_direnv.chmod(0o755)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

        output = self.parse_json(self.cli("init", "--setup-direnv", cwd=self.repo, env={**env, "DIRENV_LOG": str(allow_log)}))

        self.assertTrue(output["direnv_setup"]["available"])
        self.assertTrue(output["direnv"]["allowed"])
        self.assertEqual(
            [json.loads(line) for line in allow_log.read_text(encoding="utf-8").splitlines()],
            [["allow", str(self.repo.resolve())]],
        )

    def test_init_generated_entrypoint_can_run_cli(self):
        shutil.copytree(ROOT / "agent_mail", self.repo / "agent_mail")
        shutil.copy2(ROOT / "cli.py", self.repo / "cli.py")
        self.cli("init")

        result = subprocess.run(
            [str(self.repo / "bin" / "agent-notify"), "help", "send"],
            cwd=self.repo,
            text=True,
            capture_output=True,
            env=self.default_env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["command"], "send")

    def test_send_supports_body_sources_and_inbox_read_handle_flow(self):
        self.register_default_agents()

        inline = self.send(subject="inline", body="inline body")
        self.assertEqual(inline["status"], "unread")
        self.assertEqual(inline["body"], "inline body")
        self.assertIsNone(inline["source_session_id"])
        self.assertIsNone(inline["read_at"])
        self.assertNotIn("+00:00", inline["created_at"])

        body_file = self.repo / "body.txt"
        body_file.write_text("file body\n", encoding="utf-8")
        from_file = self.parse_json(
            self.cli(
                "send",
                "--from",
                "codex",
                "--to",
                "reasonix",
                "--subject",
                "file",
                "--body-file",
                str(body_file),
            )
        )
        self.assertEqual(from_file["body"], "file body\n")

        from_stdin = self.parse_json(
            self.cli(
                "send",
                "--from",
                "codex",
                "--to",
                "reasonix",
                "--subject",
                "stdin",
                "--body-file",
                "-",
                stdin="stdin body",
            )
        )
        self.assertEqual(from_stdin["body"], "stdin body")

        inbox = self.parse_json(self.cli("inbox", "--agent", "reasonix"))
        self.assertEqual([message["subject"] for message in inbox], ["stdin", "file", "inline"])

        read_message = self.parse_json(self.cli("read", "--agent", "reasonix", inline["id"]))
        self.assertEqual(read_message["status"], "read")
        self.assertIsNotNone(read_message["read_at"])

        handled = self.parse_json(
            self.cli("handle", "--agent", "reasonix", from_file["id"], "--note", "No follow-up needed.")
        )
        self.assertEqual(handled["status"], "handled")
        self.assertIsNotNone(handled["read_at"])
        self.assertIsNotNone(handled["handled_at"])
        self.assertEqual(handled["handled_note"], "No follow-up needed.")

        remaining = self.parse_json(self.cli("inbox", "--agent", "reasonix"))
        self.assertEqual([message["id"] for message in remaining], [from_stdin["id"], inline["id"]])

    def test_send_records_source_session_id(self):
        self.register_default_agents()

        message = self.send(source_session_id="session-123")

        self.assertEqual(message["source_session_id"], "session-123")
        stored = json.loads(
            (self.repo / ".agent-notify" / "messages" / f"{message['id']}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["source_session_id"], "session-123")

    def test_sent_defaults_to_recent_twenty_and_all_includes_archive(self):
        self.register_default_agents()
        sent_ids = [self.send(subject=f"m{i}")["id"] for i in range(25)]
        self.cli("handle", "--agent", "reasonix", sent_ids[0])

        default_sent = self.parse_json(self.cli("sent", "--agent", "codex"))
        self.assertEqual(len(default_sent), 20)
        self.assertEqual(default_sent[0]["subject"], "m24")
        self.assertNotIn(sent_ids[0], [message["id"] for message in default_sent])

        all_sent = self.parse_json(self.cli("sent", "--agent", "codex", "--all"))
        self.assertEqual(len(all_sent), 25)
        self.assertIn("handled", {message["status"] for message in all_sent})

    def test_linked_worktree_uses_same_agent_notify_root(self):
        self.register_default_agents()
        worktree = Path(self.tmp.name) / "linked"
        self.run_git(self.repo, "worktree", "add", str(worktree))

        self.cli(
            "send",
            "--from",
            "codex",
            "--to",
            "reasonix",
            "--subject",
            "from worktree",
            "--body",
            "shared queue",
            cwd=worktree,
        )

        inbox = self.parse_json(self.cli("inbox", "--agent", "reasonix", cwd=self.repo))
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["subject"], "from worktree")
        self.assertTrue((self.repo / ".agent-notify" / "messages").is_dir())
        self.assertFalse((worktree / ".agent-notify").exists())

    def test_lint_reports_bad_json_invalid_state_and_unknown_agent(self):
        self.register_default_agents()
        self.send()

        notify = self.repo / ".agent-notify"
        (notify / "messages" / "bad.json").write_text("{not json", encoding="utf-8")
        (notify / "messages" / "bad-state.json").write_text(
            json.dumps(
                {
                    "id": "bad-state",
                    "from": "codex",
                    "to": "reasonix",
                    "status": "open",
                    "sequence": 1,
                    "subject": "bad",
                    "body": "bad",
                    "created_at": "2026-06-09T00:00:00+00:00",
                    "updated_at": "2026-06-09T00:00:00+00:00",
                    "read_at": None,
                    "handled_at": None,
                    "handled_note": None,
                }
            ),
            encoding="utf-8",
        )
        (notify / "messages" / "unknown-agent.json").write_text(
            json.dumps(
                {
                    "id": "unknown-agent",
                    "from": "codex",
                    "to": "unregistered",
                    "status": "unread",
                    "sequence": 2,
                    "subject": "bad",
                    "body": "bad",
                    "created_at": "2026-06-09T00:00:00+00:00",
                    "updated_at": "2026-06-09T00:00:00+00:00",
                    "read_at": None,
                    "handled_at": None,
                    "handled_note": None,
                }
            ),
            encoding="utf-8",
        )

        lint = self.cli("lint", ok=False)
        self.assertIn("bad.json: invalid JSON", lint.stderr)
        self.assertIn("bad-state.json: invalid status", lint.stderr)
        self.assertIn("unknown-agent.json: unknown to agent", lint.stderr)

    def test_requires_non_bare_git_repository(self):
        bare = Path(self.tmp.name) / "bare.git"
        self.run_git(Path(self.tmp.name), "init", "--bare", "bare.git")

        result = self.cli("agents", cwd=bare, ok=False)
        self.assertIn("bare repositories are not supported", result.stderr)

    def test_source_uses_atomic_directory_lock_and_os_replace(self):
        source = CLI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("os.mkdir", source)
        self.assertIn("os.replace", source)
        self.assertNotIn("fcntl", source)

    def test_send_to_claude_only_queues_message(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")

        home = Path(self.tmp.name) / "home"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text('called')\n",
        )

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        result = self.cli(
            "send",
            "--from",
            "codex",
            "--to",
            "claude",
            "--subject",
            "Review request",
            "--body",
            "Review the change.",
            env=env,
        )
        message = self.parse_json(result)

        self.assertEqual(message["to"], "claude")
        self.assertEqual(message["status"], "unread")
        self.assertNotIn("claude_reply", message)
        self.assertNotIn("claude_session_id", message)
        self.assertEqual(result.stderr, "")
        self.assertFalse(call_log.exists())

    def test_send_to_non_claude_agent_does_not_start_claude(self):
        self.register_default_agents()
        home = Path(self.tmp.name) / "home"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        fake_claude = bin_dir / "claude"
        fake_claude.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text('called')\n",
            encoding="utf-8",
        )
        fake_claude.chmod(0o755)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        self.cli(
            "send",
            "--from",
            "codex",
            "--to",
            "reasonix",
            "--subject",
            "Status",
            "--body",
            "No dispatch.",
            env=env,
        )

        self.assertFalse(call_log.exists())

    def test_send_from_reasonix_to_claude_only_queues_message(self):
        self.cli("register", "reasonix", "--main")
        self.cli("register", "claude")

        home = Path(self.tmp.name) / "home"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        fake_claude = bin_dir / "claude"
        fake_claude.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text('called')\n",
            encoding="utf-8",
        )
        fake_claude.chmod(0o755)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        result = self.cli(
            "send",
            "--from",
            "reasonix",
            "--to",
            "claude",
            "--subject",
            "Status",
            "--body",
            "Queue only.",
            env=env,
        )
        message = self.parse_json(result)

        self.assertEqual(message["from"], "reasonix")
        self.assertEqual(message["to"], "claude")
        self.assertEqual(message["status"], "unread")
        self.assertNotIn("claude_reply", message)
        self.assertNotIn("claude_session_id", message)
        self.assertEqual(result.stderr, "")
        self.assertFalse(call_log.exists())

    def test_watch_run_once_resumes_latest_claude_session(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        message = self.parse_json(
            self.cli(
                "send",
                "--from",
                "codex",
                "--to",
                "claude",
                "--subject",
                "Review worktree",
                "--body",
                "Review this branch.",
                "--source-session-id",
                "codex-session-1",
            )
        )

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "11111111-1111-4111-8111-111111111111", mtime=1)
        self.write_claude_session(home, "22222222-2222-4222-8222-222222222222", mtime=2)

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-calls.jsonl"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['CLAUDE_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n",
        )

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["attempted"][0]["message_id"], message["id"])
        call = json.loads(call_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("-r", call["args"])
        self.assertEqual(call["args"][call["args"].index("-r") + 1], "22222222-2222-4222-8222-222222222222")
        self.assertIn("--dangerously-skip-permissions", call["args"])
        self.assertIn("--add-dir", call["args"])
        self.assertEqual(Path(call["cwd"]).resolve(), self.repo.resolve())
        prompt = call["args"][call["args"].index("-p") + 1]
        self.assertIn(message["id"], prompt)
        self.assertIn("source session id: codex-session-1", prompt)
        self.assertIn("read --agent claude", prompt)
        self.assertIn("handle --agent claude", prompt)
        inbox = self.parse_json(self.cli("inbox", "--agent", "claude"))
        self.assertEqual(inbox[0]["status"], "unread")
        state = json.loads((self.repo / ".agent-notify" / "watcher-state.json").read_text(encoding="utf-8"))
        self.assertIn(message["id"], state["delivered_notifications"])

        second = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))
        self.assertEqual(second["attempted"], [])
        self.assertEqual(second["skipped"][0]["reason"], "notification already delivered")
        self.assertEqual(len(call_log.read_text(encoding="utf-8").splitlines()), 1)

    def test_watch_uses_latest_project_session_from_claude_history(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        message = self.parse_json(
            self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")
        )

        home = Path(self.tmp.name) / "home"
        self.write_claude_history(
            home,
            [
                {
                    "project": str(self.repo.resolve()),
                    "sessionId": "81818181-8181-4181-8181-818181818181",
                    "timestamp": 100,
                },
                {
                    "project": "/Users/tao/.claude-mem/observer-sessions",
                    "sessionId": "observer-session",
                    "timestamp": 300,
                },
                {
                    "project": str(self.repo.resolve()),
                    "sessionId": "82828282-8282-4282-8282-828282828282",
                    "timestamp": 200,
                },
            ],
        )

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["attempted"][0]["message_id"], message["id"])
        call = json.loads(call_log.read_text(encoding="utf-8"))
        self.assertEqual(call[call.index("-r") + 1], "82828282-8282-4282-8282-828282828282")

    def test_watch_waits_when_latest_claude_session_is_busy(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        message = self.parse_json(
            self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")
        )

        home = Path(self.tmp.name) / "home"
        session_id = "83838383-8383-4383-8383-838383838383"
        self.write_claude_history(
            home,
            [{"project": str(self.repo.resolve()), "sessionId": session_id, "timestamp": 200}],
        )
        active_sessions = home / ".claude" / "sessions"
        active_sessions.mkdir(parents=True)
        (active_sessions / f"{os.getpid()}.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "sessionId": session_id,
                    "cwd": str(self.repo.resolve()),
                    "status": "busy",
                }
            ),
            encoding="utf-8",
        )
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text('called')\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["skipped"][0]["message_id"], message["id"])
        self.assertEqual(output["skipped"][0]["reason"], "latest repository session is not safe to resume")
        self.assertFalse(call_log.exists())

    def test_watch_routes_reply_to_original_source_session(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        original = self.parse_json(
            self.cli(
                "send",
                "--from",
                "claude",
                "--to",
                "codex",
                "--source-session-id",
                "84848484-8484-4484-8484-848484848484",
                "--subject",
                "Review result",
                "--body",
                "Result",
            )
        )
        reply = self.parse_json(
            self.cli(
                "send",
                "--from",
                "codex",
                "--to",
                "claude",
                "--subject",
                "re: Review result",
                "--body",
                f"In reply to {original['id']}\n\nFollow-up",
            )
        )

        home = Path(self.tmp.name) / "home"
        self.write_claude_history(
            home,
            [
                {
                    "project": str(self.repo.resolve()),
                    "sessionId": "84848484-8484-4484-8484-848484848484",
                    "timestamp": 100,
                },
                {
                    "project": str(self.repo.resolve()),
                    "sessionId": "85858585-8585-4585-8585-858585858585",
                    "timestamp": 200,
                },
            ],
        )
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["attempted"][0]["message_id"], reply["id"])
        call = json.loads(call_log.read_text(encoding="utf-8"))
        self.assertEqual(call[call.index("-r") + 1], "84848484-8484-4484-8484-848484848484")

    def test_watch_creates_notification_session_when_resume_is_missing(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        self.cli(
            "send",
            "--from",
            "codex",
            "--to",
            "claude",
            "--subject",
            "Review request",
            "--body",
            "Review the change.",
        )

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "44444444-4444-4444-8444-444444444444", mtime=1)

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-calls.jsonl"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['CLAUDE_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if '-r' in sys.argv and sys.argv[sys.argv.index('-r') + 1] == "
            "'44444444-4444-4444-8444-444444444444':\n"
            "    print('No conversation found with session ID', file=sys.stderr)\n"
            "    raise SystemExit(7)\n",
        )

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))
        inbox = self.parse_json(self.cli("inbox", "--agent", "claude"))
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["status"], "unread")
        self.assertEqual(output["attempted"][0]["message_id"], inbox[0]["id"])

        calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][calls[0].index("-r") + 1], "44444444-4444-4444-8444-444444444444")
        self.assertIn("--session-id", calls[1])

        watcher_state = json.loads(
            (self.repo / ".agent-notify" / "watcher-state.json").read_text(encoding="utf-8")
        )
        self.assertNotIn(inbox[0]["id"], watcher_state["retries"])

    def test_watch_does_not_create_claude_session_for_generic_failure(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "45454545-4545-4545-8545-454545454545", mtime=1)
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-calls.jsonl"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['CLAUDE_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "print('API Error: ConnectionRefused', file=sys.stderr)\n"
            "raise SystemExit(8)\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["failed"][0]["returncode"], 8)
        self.assertIn("ConnectionRefused", output["failed"][0]["stderr"])
        self.assertEqual(len(call_log.read_text(encoding="utf-8").splitlines()), 1)

    def test_watch_keeps_unread_when_new_claude_session_fails(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        message = self.parse_json(
            self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")
        )

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "46464646-4646-4646-8646-464646464646", mtime=1)
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-calls.jsonl"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['CLAUDE_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if '-r' in sys.argv:\n"
            "    print('No conversation found with session ID', file=sys.stderr)\n"
            "    raise SystemExit(7)\n"
            "print('API Error: ConnectionRefused', file=sys.stderr)\n"
            "raise SystemExit(8)\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["failed"][0]["returncode"], 8)
        self.assertIn("ConnectionRefused", output["failed"][0]["stderr"])
        self.assertEqual(len(call_log.read_text(encoding="utf-8").splitlines()), 2)
        inbox = self.parse_json(self.cli("inbox", "--agent", "claude"))
        self.assertEqual(inbox[0]["status"], "unread")
        watcher_state = json.loads(
            (self.repo / ".agent-notify" / "watcher-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(watcher_state["retries"][message["id"]]["attempts"], 1)

    def test_watch_run_once_ignores_claude_mem_observer_session(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "55555555-5555-4555-8555-555555555555", mtime=1)
        self.write_claude_session(
            home,
            "66666666-6666-4666-8666-666666666666",
            content='{"cwd": "/Users/tao/.claude-mem/observer-sessions", "message": "You are a Claude-Mem, a specialized observer tool for creating searchable memory"}\n',
            mtime=2,
        )

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        self.cli("watch", "run", "--once", "--agents", "claude", env=env)

        call = json.loads(call_log.read_text(encoding="utf-8"))
        self.assertEqual(call[call.index("-r") + 1], "55555555-5555-4555-8555-555555555555")

    def test_watch_run_once_resumes_latest_codex_repository_session(self):
        self.cli("register", "claude", "--main")
        self.cli("register", "codex")
        message = self.parse_json(
            self.cli(
                "send",
                "--from",
                "claude",
                "--to",
                "codex",
                "--source-session-id",
                "claude-source-123",
                "--subject",
                "Reply request",
                "--body",
                "In reply to deadbeefdeadbeefdeadbeefdeadbeef\n\nPlease follow up.",
            )
        )

        home = Path(self.tmp.name) / "home"
        repo_session_id = "91919191-9191-4191-8191-919191919191"
        observer_session_id = "92929292-9292-4292-8292-929292929292"
        self.write_codex_session_index(
            home,
            [
                {
                    "id": repo_session_id,
                    "thread_name": "Repo session",
                    "updated_at": "2026-06-11T00:00:00Z",
                },
                {
                    "id": observer_session_id,
                    "thread_name": "Observer session",
                    "updated_at": "2026-06-11T00:01:00Z",
                },
            ],
        )
        self.write_codex_rollout(home, repo_session_id, self.repo.resolve(), mtime=1)
        self.write_codex_rollout(home, observer_session_id, home / ".codex-mem" / "observer-sessions", mtime=2)

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "codex-calls.jsonl"
        self.write_fake_codex(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['CODEX_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CODEX_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "codex", env=env))

        self.assertEqual(output["attempted"][0]["message_id"], message["id"])
        call = json.loads(call_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(call["args"][:3], ["exec", "resume", repo_session_id])
        self.assertIn(message["id"], call["args"][3])
        self.assertIn("source session id: claude-source-123", call["args"][3])
        self.assertIn("read --agent codex", call["args"][3])
        self.assertEqual(Path(call["cwd"]).resolve(), self.repo.resolve())

    def test_watch_run_once_skips_active_codex_repository_session(self):
        self.cli("register", "claude", "--main")
        self.cli("register", "codex")
        message = self.parse_json(
            self.cli("send", "--from", "claude", "--to", "codex", "--subject", "Reply", "--body", "Body")
        )

        home = Path(self.tmp.name) / "home"
        session_id = "93939393-9393-4393-8393-939393939393"
        self.write_codex_session_index(
            home,
            [{"id": session_id, "thread_name": "Repo session", "updated_at": "2026-06-11T00:00:00Z"}],
        )
        self.write_codex_rollout(home, session_id, self.repo.resolve(), mtime=1)
        self.write_codex_process_manager(
            home,
            [
                {
                    "conversationId": session_id,
                    "cwd": str(self.repo.resolve()),
                    "command": "codex exec resume",
                    "osPid": os.getpid(),
                    "processId": str(os.getpid()),
                    "startedAtMs": int(time.time() * 1000),
                    "updatedAtMs": int(time.time() * 1000),
                }
            ],
        )

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "codex-call.json"
        self.write_fake_codex(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['CODEX_CALL_LOG']).write_text('called')\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CODEX_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "codex", env=env))

        self.assertEqual(output["skipped"][0]["message_id"], message["id"])
        self.assertEqual(output["skipped"][0]["reason"], "latest repository session is not safe to resume")
        self.assertFalse(call_log.exists())

    def test_watch_run_once_ignores_non_repository_codex_sessions(self):
        self.cli("register", "claude", "--main")
        self.cli("register", "codex")
        self.cli("send", "--from", "claude", "--to", "codex", "--subject", "Reply", "--body", "Body")

        home = Path(self.tmp.name) / "home"
        observer_session_id = "94949494-9494-4494-8494-949494949494"
        self.write_codex_session_index(
            home,
            [{"id": observer_session_id, "thread_name": "Observer", "updated_at": "2026-06-11T00:00:00Z"}],
        )
        self.write_codex_rollout(home, observer_session_id, home / ".codex-mem" / "observer-sessions", mtime=1)

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "codex-call.json"
        self.write_fake_codex(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['CODEX_CALL_LOG']).write_text('called')\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CODEX_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "codex", env=env))

        self.assertEqual(output["skipped"][0]["reason"], "no safe repository session found")
        self.assertFalse(call_log.exists())

    def test_watch_does_not_reject_project_session_that_mentions_claude_mem(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")

        home = Path(self.tmp.name) / "home"
        content = (
            json.dumps({"cwd": str(self.repo.resolve()), "message": "normal project turn"})
            + "\n"
            + json.dumps({"message": "Discuss: You are a Claude-Mem, a specialized observer tool for creating searchable memory"})
            + "\n"
        )
        self.write_claude_session(home, "67676767-6767-4767-8767-676767676767", content=content, mtime=1)

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-call.json"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CLAUDE_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)

        self.cli("watch", "run", "--once", "--agents", "claude", env=env)

        call = json.loads(call_log.read_text(encoding="utf-8"))
        self.assertEqual(call[call.index("-r") + 1], "67676767-6767-4767-8767-676767676767")

    def test_watch_run_once_resumes_latest_reasonix_session(self):
        self.register_default_agents()
        message = self.send(subject="Implement", body="Handle this.", source_session_id="codex-session-2")

        home = Path(self.tmp.name) / "home"
        sessions = home / "Library" / "Application Support" / "reasonix" / "sessions"
        sessions.mkdir(parents=True)
        older = sessions / "older.jsonl"
        newer = sessions / "newer.jsonl"
        older.write_text("{}\n", encoding="utf-8")
        newer.write_text(json.dumps({"cwd": str(self.repo.resolve())}) + "\n", encoding="utf-8")
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "reasonix-call.json"
        fake_reasonix = bin_dir / "reasonix"
        fake_reasonix.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['REASONIX_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        fake_reasonix.chmod(0o755)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["REASONIX_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "reasonix", env=env))

        self.assertEqual(output["attempted"][0]["message_id"], message["id"])
        call = json.loads(call_log.read_text(encoding="utf-8"))
        self.assertEqual(call[:3], ["run", "--resume", str(newer)])
        self.assertIn(message["id"], call[3])
        self.assertIn("source session id: codex-session-2", call[3])

    def test_watch_run_once_uses_registered_agent_type_for_custom_name(self):
        self.cli("register", "coordinator", "--type", "codex", "--main")
        self.cli("register", "reasonix-web", "--type", "reasonix")
        message = self.parse_json(
            self.cli(
                "send",
                "--from",
                "coordinator",
                "--to",
                "reasonix-web",
                "--subject",
                "Implement",
                "--body",
                "Handle this.",
            )
        )

        home = Path(self.tmp.name) / "home"
        sessions = home / "Library" / "Application Support" / "reasonix" / "sessions"
        sessions.mkdir(parents=True)
        session = sessions / "reasonix-web-session.jsonl"
        session.write_text(json.dumps({"cwd": str(self.repo.resolve())}) + "\n", encoding="utf-8")

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "reasonix-call.json"
        fake_reasonix = bin_dir / "reasonix"
        fake_reasonix.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['REASONIX_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        fake_reasonix.chmod(0o755)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["REASONIX_CALL_LOG"] = str(call_log)

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "reasonix-web", env=env))

        self.assertEqual(output["attempted"][0]["agent"], "reasonix-web")
        self.assertEqual(output["attempted"][0]["message_id"], message["id"])
        call = json.loads(call_log.read_text(encoding="utf-8"))
        self.assertEqual(call[:3], ["run", "--resume", str(session)])
        self.assertIn("read --agent reasonix-web", call[3])

    def test_watch_run_once_serializes_same_session_with_lock(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        first_message = self.parse_json(
            self.cli("send", "--from", "codex", "--to", "claude", "--subject", "first", "--body", "first")
        )

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "77777777-7777-4777-8777-777777777777", mtime=1)
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        call_log = Path(self.tmp.name) / "claude-calls.jsonl"
        started = Path(self.tmp.name) / "started"
        release = Path(self.tmp.name) / "release"
        self.write_fake_claude(
            bin_dir,
            "#!/usr/bin/env python3\n"
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "with Path(os.environ['CLAUDE_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "Path(os.environ['STARTED']).write_text('1')\n"
            "release = Path(os.environ['RELEASE'])\n"
            "while not release.exists():\n"
            "    time.sleep(0.05)\n",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CLAUDE_CALL_LOG"] = str(call_log)
        env["STARTED"] = str(started)
        env["RELEASE"] = str(release)

        first = subprocess.Popen(
            [sys.executable, str(CLI_SCRIPT), "watch", "run", "--once", "--agents", "claude"],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(started.exists())

        second_message = self.parse_json(
            self.cli("send", "--from", "codex", "--to", "claude", "--subject", "second", "--body", "second")
        )
        skipped = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))
        self.assertEqual(skipped["skipped"][0]["reason"], "session is already being resumed")
        self.assertEqual(len(call_log.read_text(encoding="utf-8").splitlines()), 1)

        release.write_text("go", encoding="utf-8")
        stdout, stderr = first.communicate(timeout=5)
        self.assertEqual(first.returncode, 0, f"stdout={stdout}\nstderr={stderr}")

        self.cli("handle", "--agent", "claude", first_message["id"], "--note", "first completed")
        self.cli("watch", "run", "--once", "--agents", "claude", env=env)
        calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertIn(second_message["id"], calls[1][calls[1].index("-p") + 1])

    def test_watch_run_once_keeps_unread_when_cli_is_missing(self):
        self.cli("register", "codex", "--main")
        self.cli("register", "claude")
        self.cli("send", "--from", "codex", "--to", "claude", "--subject", "Review", "--body", "Body")

        home = Path(self.tmp.name) / "home"
        self.write_claude_session(home, "78787878-7878-4787-8787-787878787878", mtime=1)
        empty_bin = Path(self.tmp.name) / "empty-bin"
        empty_bin.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = os.pathsep.join([str(empty_bin), str(Path(shutil.which("git")).parent)])

        output = self.parse_json(self.cli("watch", "run", "--once", "--agents", "claude", env=env))

        self.assertEqual(output["failed"][0]["returncode"], None)
        self.assertIn("claude", output["failed"][0]["stderr"])
        inbox = self.parse_json(self.cli("inbox", "--agent", "claude"))
        self.assertEqual(inbox[0]["status"], "unread")

    def test_watch_install_status_and_uninstall_manage_launchd_plist(self):
        self.cli("register", "codex", "--main")
        home = Path(self.tmp.name) / "home"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        launchctl_log = Path(self.tmp.name) / "launchctl.jsonl"
        fake_launchctl = bin_dir / "launchctl"
        fake_launchctl.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['LAUNCHCTL_LOG']).open('a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        fake_launchctl.chmod(0o755)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["LAUNCHCTL_LOG"] = str(launchctl_log)

        installed = self.parse_json(
            self.cli("watch", "install", "--agents", "claude,reasonix", "--interval", "7", env=env)
        )
        plist_path = Path(installed["plist"])
        self.assertTrue(plist_path.exists())
        self.assertIn("com.dplake.agent-notify.watcher", installed["label"])
        plist_text = plist_path.read_text(encoding="utf-8")
        self.assertIn("<string>watch</string>", plist_text)
        self.assertIn("<string>run</string>", plist_text)
        self.assertIn("<string>claude,reasonix</string>", plist_text)
        self.assertIn("<string>7</string>", plist_text)
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        watcher_executable = Path(installed["executable"])
        self.assertEqual(watcher_executable.name, "agent-notify-watcher")
        self.assertTrue(watcher_executable.is_symlink())
        self.assertEqual(Path(plist["ProgramArguments"][0]), watcher_executable)
        self.assertIn("--agents", plist["ProgramArguments"])
        self.assertEqual(plist["EnvironmentVariables"]["HOME"], str(home))
        self.assertEqual(plist["EnvironmentVariables"]["PATH"], env["PATH"])

        status = self.parse_json(self.cli("watch", "status", env=env))
        self.assertTrue(status["installed"])
        self.assertTrue(status["loaded"])

        uninstalled = self.parse_json(self.cli("watch", "uninstall", env=env))
        self.assertFalse(plist_path.exists())
        self.assertFalse(watcher_executable.exists())
        self.assertFalse(uninstalled["installed"])

        calls = [json.loads(line) for line in launchctl_log.read_text(encoding="utf-8").splitlines()]
        self.assertIn(["load", str(plist_path)], calls)
        self.assertIn(["list", installed["label"]], calls)
        self.assertIn(["unload", str(plist_path)], calls)

    def test_watch_install_omits_agents_filter_by_default(self):
        self.cli("register", "codex", "--main")
        home = Path(self.tmp.name) / "home"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        fake_launchctl = bin_dir / "launchctl"
        fake_launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_launchctl.chmod(0o755)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

        installed = self.parse_json(self.cli("watch", "install", "--interval", "7", env=env))

        with Path(installed["plist"]).open("rb") as fh:
            plist = plistlib.load(fh)
        self.assertNotIn("--agents", plist["ProgramArguments"])
        self.assertIn("--interval", plist["ProgramArguments"])

    def test_watch_cleanup_removes_only_stale_launchd_plists(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import launchd

        home = Path(self.tmp.name) / "home"
        launch_agents = home / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True)
        root = self.repo / ".agent-notify"
        root.mkdir()
        other_repo = Path(self.tmp.name) / "other-repo"
        other_repo.mkdir()
        stale_repo = Path(self.tmp.name) / "stale-repo"
        stale_repo.mkdir()
        valid_executable = Path(sys.executable)
        valid_script = ROOT / "cli.py"
        calls = []

        def write_plist(label, working_directory, executable=valid_executable, script=valid_script):
            path = launch_agents / f"{label}.plist"
            with path.open("wb") as fh:
                plistlib.dump(
                    {
                        "Label": label,
                        "ProgramArguments": [str(executable), str(script), "watch", "run"],
                        "WorkingDirectory": str(working_directory),
                    },
                    fh,
                )
            return path

        current = write_plist(launchd.watcher_label(root), self.repo)
        other = write_plist("com.dplake.agent-notify.watcher.otherproject", other_repo)
        stale = write_plist("com.dplake.agent-notify.watcher.stale", stale_repo)
        stale_repo.rmdir()

        def fake_run(args, text=True, capture_output=True):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            mock.patch("agent_mail.launchd.sys.platform", "darwin"),
            mock.patch("agent_mail.launchd.Path.home", return_value=home),
            mock.patch("agent_mail.launchd.subprocess.run", side_effect=fake_run),
        ):
            dry_run = launchd.cleanup_watchers(root, dry_run=True)
            cleaned = launchd.cleanup_watchers(root, dry_run=False)

        self.assertTrue(current.exists())
        self.assertTrue(other.exists())
        self.assertFalse(stale.exists())
        self.assertEqual([item["label"] for item in dry_run["removed"]], ["com.dplake.agent-notify.watcher.stale"])
        self.assertEqual([item["label"] for item in cleaned["removed"]], ["com.dplake.agent-notify.watcher.stale"])
        self.assertEqual({item["label"] for item in cleaned["kept"]}, {launchd.watcher_label(root), "com.dplake.agent-notify.watcher.otherproject"})
        self.assertIn(["launchctl", "unload", str(stale)], calls)

    def test_windows_task_scheduler_backend_writes_launcher_and_uses_schtasks(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import windows

        root = self.repo / ".agent-notify"
        root.mkdir()
        calls = []

        def fake_run(args, text=True, capture_output=True):
            calls.append(args)
            if args[:2] == ["schtasks", "/Query"]:
                return subprocess.CompletedProcess(args, 0, "Status: Ready\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            mock.patch("agent_mail.windows.sys.platform", "win32"),
            mock.patch("agent_mail.windows.subprocess.run", side_effect=fake_run),
        ):
            installed = windows.install_watcher(root, "claude,reasonix", 7, 1800)
            launcher_path = Path(installed["launcher"])
            self.assertTrue(launcher_path.exists())
            launcher = launcher_path.read_text(encoding="utf-8")
            status = windows.watcher_status(root)
            uninstalled = windows.uninstall_watcher(root)

        self.assertIn("agent-notify.ps1", launcher)
        self.assertIn("claude,reasonix", launcher)
        self.assertIn("'7'", launcher)
        self.assertTrue(status["installed"])
        self.assertTrue(status["loaded"])
        self.assertFalse(launcher_path.exists())
        self.assertFalse(uninstalled["installed"])
        self.assertIn(
            ["schtasks", "/Create", "/SC", "ONLOGON", "/TN", installed["label"]],
            [call[:6] for call in calls],
        )
        self.assertIn(["schtasks", "/Query", "/TN", installed["label"], "/FO", "LIST", "/V"], calls)
        self.assertIn(["schtasks", "/Delete", "/TN", installed["label"], "/F"], calls)

    def test_windows_watcher_launcher_omits_agents_filter_by_default(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import windows

        root = self.repo / ".agent-notify"
        root.mkdir()

        with mock.patch("agent_mail.windows.sys.platform", "win32"), mock.patch(
            "agent_mail.windows.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ):
            installed = windows.install_watcher(root, "", 7, 1800)

        launcher = Path(installed["launcher"]).read_text(encoding="utf-8")
        self.assertNotIn("'--agents'", launcher)
        self.assertIn("'--interval'", launcher)

    def test_watch_cleanup_removes_only_stale_windows_tasks(self):
        sys.path.insert(0, str(ROOT))
        from agent_mail import windows

        root = self.repo / ".agent-notify"
        root.mkdir()
        other_launcher = Path(self.tmp.name) / "other.ps1"
        other_launcher.write_text("echo other\n", encoding="utf-8")
        stale_launcher = Path(self.tmp.name) / "missing.ps1"
        current_launcher = windows.launcher_path(root)
        current_launcher.write_text("echo current\n", encoding="utf-8")
        current_label = windows.watcher_label(root)
        csv_output = (
            '"TaskName","Task To Run"\n'
            f'"\\{current_label}","powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{current_launcher}"""\n'
            f'"\\DPLake-agent-notify-watcher-other","powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{other_launcher}"""\n'
            f'"\\DPLake-agent-notify-watcher-stale","powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{stale_launcher}"""\n'
        )
        calls = []

        def fake_run(args, text=True, capture_output=True):
            calls.append(args)
            if args[:3] == ["schtasks", "/Query", "/FO"]:
                return subprocess.CompletedProcess(args, 0, csv_output, "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            mock.patch("agent_mail.windows.sys.platform", "win32"),
            mock.patch("agent_mail.windows.subprocess.run", side_effect=fake_run),
        ):
            dry_run = windows.cleanup_watchers(root, dry_run=True)
            cleaned = windows.cleanup_watchers(root, dry_run=False)

        self.assertEqual([item["label"] for item in dry_run["removed"]], ["DPLake-agent-notify-watcher-stale"])
        self.assertEqual([item["label"] for item in cleaned["removed"]], ["DPLake-agent-notify-watcher-stale"])
        self.assertEqual({item["label"] for item in cleaned["kept"]}, {current_label, "DPLake-agent-notify-watcher-other"})
        self.assertIn(["schtasks", "/Delete", "/TN", "\\DPLake-agent-notify-watcher-stale", "/F"], calls)


if __name__ == "__main__":
    unittest.main()
