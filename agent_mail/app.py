"""Argument parser and top-level CLI entry."""

import argparse
import json
import sys

from .constants import DEFAULT_INIT_AGENTS
from .direnv_setup import command_setup_direnv
from .errors import NotifyError
from .help import command_help
from .init_project import command_init
from .lint import command_lint
from .messages import command_handle, command_inbox, command_read, command_send, command_sent
from .registry import command_agents, command_register
from .watch_service import command_watch_install, command_watch_status, command_watch_uninstall
from .watcher import command_watch_run


def build_parser():
    parser = argparse.ArgumentParser(description="Manage local agent notifications.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register")
    register.add_argument("agent")
    register.add_argument("--type", dest="agent_type")
    register.set_defaults(func=command_register)

    agents = subparsers.add_parser("agents")
    agents.add_argument("--details", action="store_true")
    agents.set_defaults(func=command_agents)

    help_parser = subparsers.add_parser("help")
    help_parser.add_argument("topic", nargs="*")
    help_parser.set_defaults(func=command_help)

    init = subparsers.add_parser("init")
    init.add_argument("--agents", default=DEFAULT_INIT_AGENTS)
    init.add_argument("--no-gitignore", action="store_true")
    init.add_argument("--install-watcher", action="store_true")
    init.add_argument("--watch-agents")
    init.add_argument("--interval", type=float, default=5)
    init.add_argument("--timeout", type=float, default=1800)
    init.add_argument("--setup-direnv", action="store_true")
    init.add_argument("--print-agent-rules", action="store_true")
    init.set_defaults(func=command_init)

    setup_direnv = subparsers.add_parser("setup-direnv")
    setup_direnv.add_argument("--shell")
    setup_direnv.add_argument("--status", action="store_true")
    setup_direnv.set_defaults(func=command_setup_direnv)

    send = subparsers.add_parser("send")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", required=True)
    send.add_argument("--subject", required=True)
    send.add_argument("--source-session-id")
    body = send.add_mutually_exclusive_group()
    body.add_argument("--body")
    body.add_argument("--body-file")
    send.set_defaults(func=command_send)

    inbox = subparsers.add_parser("inbox")
    inbox.add_argument("--agent", required=True)
    inbox.set_defaults(func=command_inbox)

    sent = subparsers.add_parser("sent")
    sent.add_argument("--agent", required=True)
    sent.add_argument("--all", action="store_true")
    sent.set_defaults(func=command_sent)

    read = subparsers.add_parser("read")
    read.add_argument("--agent", required=True)
    read.add_argument("message_id")
    read.set_defaults(func=command_read)

    handle = subparsers.add_parser("handle")
    handle.add_argument("--agent", required=True)
    handle.add_argument("message_id")
    handle.add_argument("--note")
    handle.set_defaults(func=command_handle)

    lint = subparsers.add_parser("lint")
    lint.set_defaults(func=command_lint)

    watch = subparsers.add_parser("watch")
    watch_subparsers = watch.add_subparsers(dest="watch_command", required=True)

    watch_run = watch_subparsers.add_parser("run")
    watch_run.add_argument("--agents")
    watch_run.add_argument("--interval", type=float, default=5)
    watch_run.add_argument("--timeout", type=float, default=1800)
    watch_run.add_argument("--once", action="store_true")
    watch_run.set_defaults(func=command_watch_run)

    watch_install = watch_subparsers.add_parser("install")
    watch_install.add_argument("--agents", default="")
    watch_install.add_argument("--interval", type=float, default=5)
    watch_install.add_argument("--timeout", type=float, default=1800)
    watch_install.set_defaults(func=command_watch_install)

    watch_status = watch_subparsers.add_parser("status")
    watch_status.set_defaults(func=command_watch_status)

    watch_uninstall = watch_subparsers.add_parser("uninstall")
    watch_uninstall.set_defaults(func=command_watch_uninstall)

    return parser

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except (NotifyError, json.JSONDecodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return result or 0


if __name__ == "__main__":
    raise SystemExit(main())
