"""Machine-readable command help."""

from .constants import HELP_DOCS, HELP_INTERFACES
from .errors import NotifyError
from .utils import print_json


def command_help(args):
    if args.topic:
        topic = " ".join(args.topic)
        if topic not in HELP_INTERFACES:
            raise NotifyError(f"unknown help topic: {topic}")
        print_json({"command": topic, **HELP_INTERFACES[topic], "docs": HELP_DOCS})
        return
    print_json(
        {
            "tool": "agent-notify",
            "purpose": "Local Git-repository-scoped notification queue and optional session wakeup watcher for cooperating agents.",
            "key_rules": [
                "send only queues a notification; it does not prove the recipient processed it",
                "agent names are inbox addresses",
                "agent types select wakeup drivers: codex, claude, or reasonix",
                "handled closes the notification lifecycle, not the underlying implementation task",
                "do not edit .agent-notify/ files directly",
            ],
            "interfaces": {name: data["purpose"] for name, data in HELP_INTERFACES.items()},
            "docs": HELP_DOCS,
        }
    )
