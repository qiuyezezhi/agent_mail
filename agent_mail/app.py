"""Argument parser and top-level CLI entry."""

import argparse
import json
import sys

from .constants import DEFAULT_INIT_AGENTS, HELP_INTERFACES
from .direnv_setup import command_setup_direnv
from .errors import NotifyError
from .help import command_help
from .init_project import command_init
from .lint import command_lint
from .messages import command_handle, command_inbox, command_read, command_send, command_sent
from .registry import command_agents, command_register, command_set_main
from .watch_service import command_watch_install, command_watch_status, command_watch_uninstall
from .watcher import command_watch_run


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


def help_text(topic, parameter=None):
    data = HELP_INTERFACES[topic]
    if parameter is None:
        return data["purpose"]
    return data["parameters"].get(parameter)


def add_parser(subparsers, topic, name=None):
    parser_name = name or topic
    return subparsers.add_parser(
        parser_name,
        help=help_text(topic),
        description=help_text(topic),
        formatter_class=HelpFormatter,
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Manage local agent notifications.",
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="<command>",
    )

    register = add_parser(subparsers, "register")
    register.add_argument("agent", help=help_text("register", "<agent-name>"))
    register.add_argument("--type", dest="agent_type", help=help_text("register", "--type"))
    register.add_argument("--main", action="store_true", help=help_text("register", "--main"))
    register.set_defaults(func=command_register)

    agents = add_parser(subparsers, "agents")
    agents.add_argument("--details", action="store_true", help=help_text("agents", "--details"))
    agents.set_defaults(func=command_agents)

    set_main = add_parser(subparsers, "set-main")
    set_main.add_argument("agent", help=help_text("set-main", "<agent-name>"))
    set_main.set_defaults(func=command_set_main)

    help_parser = add_parser(subparsers, "help")
    help_parser.add_argument("topic", nargs="*", help="Optional command topic, for example send or watch run.")
    help_parser.set_defaults(func=command_help)

    init = add_parser(subparsers, "init")
    init.add_argument("--agents", default=DEFAULT_INIT_AGENTS, help=help_text("init", "--agents"))
    init.add_argument("--no-gitignore", action="store_true", help=help_text("init", "--no-gitignore"))
    init.add_argument("--install-watcher", action="store_true", help=help_text("init", "--install-watcher"))
    init.add_argument("--watch-agents", help=help_text("init", "--watch-agents"))
    init.add_argument("--interval", type=float, default=5, help=help_text("init", "--interval"))
    init.add_argument("--timeout", type=float, default=1800, help=help_text("init", "--timeout"))
    init.add_argument("--setup-direnv", action="store_true", help=help_text("init", "--setup-direnv"))
    init.add_argument("--print-agent-rules", action="store_true", help=help_text("init", "--print-agent-rules"))
    init.set_defaults(func=command_init)

    setup_direnv = add_parser(subparsers, "setup-direnv")
    setup_direnv.add_argument("--shell", help=help_text("setup-direnv", "--shell"))
    setup_direnv.add_argument("--status", action="store_true", help=help_text("setup-direnv", "--status"))
    setup_direnv.set_defaults(func=command_setup_direnv)

    send = add_parser(subparsers, "send")
    send.add_argument("--from", dest="sender", required=True, help=help_text("send", "--from"))
    send.add_argument("--to", required=True, help=help_text("send", "--to"))
    send.add_argument("--subject", required=True, help=help_text("send", "--subject"))
    send.add_argument("--source-session-id", help=help_text("send", "--source-session-id"))
    body = send.add_mutually_exclusive_group()
    body.add_argument("--body", help=help_text("send", "--body"))
    body.add_argument("--body-file", help=help_text("send", "--body-file"))
    send.set_defaults(func=command_send)

    inbox = add_parser(subparsers, "inbox")
    inbox.add_argument("--agent", required=True, help=help_text("inbox", "--agent"))
    inbox.set_defaults(func=command_inbox)

    sent = add_parser(subparsers, "sent")
    sent.add_argument("--agent", required=True, help=help_text("sent", "--agent"))
    sent.add_argument("--all", action="store_true", help=help_text("sent", "--all"))
    sent.set_defaults(func=command_sent)

    read = add_parser(subparsers, "read")
    read.add_argument("--agent", required=True, help=help_text("read", "--agent"))
    read.add_argument("message_id", help=help_text("read", "<message-id>"))
    read.set_defaults(func=command_read)

    handle = add_parser(subparsers, "handle")
    handle.add_argument("--agent", required=True, help=help_text("handle", "--agent"))
    handle.add_argument("message_id", help=help_text("handle", "<message-id>"))
    handle.add_argument("--note", help=help_text("handle", "--note"))
    handle.set_defaults(func=command_handle)

    lint = add_parser(subparsers, "lint")
    lint.set_defaults(func=command_lint)

    watch = subparsers.add_parser(
        "watch",
        help="Run or manage the background watcher.",
        description="Run or manage the background watcher.",
        formatter_class=HelpFormatter,
    )
    watch_subparsers = watch.add_subparsers(dest="watch_command", required=True, metavar="<watch-command>")

    watch_run = add_parser(watch_subparsers, "watch run", name="run")
    watch_run.add_argument("--agents", help=help_text("watch run", "--agents"))
    watch_run.add_argument("--interval", type=float, default=5, help=help_text("watch run", "--interval"))
    watch_run.add_argument("--timeout", type=float, default=1800, help=help_text("watch run", "--timeout"))
    watch_run.add_argument("--once", action="store_true", help=help_text("watch run", "--once"))
    watch_run.set_defaults(func=command_watch_run)

    watch_install = add_parser(watch_subparsers, "watch install", name="install")
    watch_install.add_argument("--agents", default="", help=help_text("watch install", "--agents"))
    watch_install.add_argument("--interval", type=float, default=5, help=help_text("watch install", "--interval"))
    watch_install.add_argument("--timeout", type=float, default=1800, help=help_text("watch install", "--timeout"))
    watch_install.set_defaults(func=command_watch_install)

    watch_status = add_parser(watch_subparsers, "watch status", name="status")
    watch_status.set_defaults(func=command_watch_status)

    watch_uninstall = add_parser(watch_subparsers, "watch uninstall", name="uninstall")
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
