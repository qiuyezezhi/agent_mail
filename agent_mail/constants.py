"""Constants for the agent mail CLI."""

STATUSES = {"unread", "read", "handled"}
CLAUDE_MEM_MARKER = "You are a Claude-Mem, a specialized observer tool for creating searchable memory"
WATCHER_LABEL_PREFIX = "com.dplake.agent-notify.watcher"
SUPPORTED_AGENT_TYPES = {"claude", "reasonix", "codex"}
DEFAULT_INIT_AGENTS = ""
HELP_DOCS = {
    "readme": "README.md",
    "cli_reference": "docs/cli-reference.md",
    "agent_rules": "docs/agent-rules.md",
}
HELP_INTERFACES = {
    "init": {
        "purpose": "Initialize the local notification queue for this Git repository.",
        "parameters": {
            "--agents": "Optional comma-separated name:type registrations, for example claude-reviewer:claude.",
            "--no-gitignore": "Do not add .agent-notify/ to .gitignore.",
            "--install-watcher": "Install the background watcher after initialization.",
            "--watch-agents": "Comma-separated agent names monitored by watcher install.",
            "--interval": "Watcher polling interval in seconds. Default: 5.",
            "--timeout": "Per resume command timeout in seconds. Default: 1800.",
            "--setup-direnv": "Install and configure direnv for the current platform shell before finalizing init.",
            "--print-agent-rules": "Include a copyable project rules block in the JSON output.",
        },
    },
    "setup-direnv": {
        "purpose": "Install direnv when needed and hook it into the recommended shell for the current platform.",
        "parameters": {
            "--shell": "Override the target shell. macOS supports zsh, Windows supports pwsh.",
            "--status": "Report current direnv and shell-hook status without changing anything.",
        },
    },
    "register": {
        "purpose": "Register an agent inbox name and bind it to a wakeup driver type.",
        "parameters": {
            "<agent-name>": "Required inbox address used by send, inbox, read, handle, and watch.",
            "--type": "Required for custom names. One of codex, claude, or reasonix.",
            "--main": "Mark this agent as the single global main-agent.",
        },
    },
    "agents": {
        "purpose": "List registered agent names, optionally with their wakeup types.",
        "parameters": {
            "--details": "Return objects with name and type instead of names only.",
        },
    },
    "set-main": {
        "purpose": "Switch the single global main-agent to an already registered agent.",
        "parameters": {
            "<agent-name>": "Required registered agent name that will become the new main-agent.",
        },
    },
    "send": {
        "purpose": "Queue a notification for a registered agent.",
        "parameters": {
            "--from": "Required sender agent name.",
            "--to": "Required recipient agent name.",
            "--subject": "Required notification subject.",
            "--body": "Inline notification body.",
            "--body-file": "Read body from a file, or from stdin when set to -.",
            "--source-session-id": "Optional sender session id used by reply routing.",
        },
    },
    "inbox": {
        "purpose": "List active messages addressed to an agent.",
        "parameters": {
            "--agent": "Required recipient agent name.",
        },
    },
    "read": {
        "purpose": "Read one message and mark it read when it was unread.",
        "parameters": {
            "--agent": "Required recipient agent name.",
            "<message-id>": "Required message id.",
        },
    },
    "handle": {
        "purpose": "Mark one message handled and move it to the archive.",
        "parameters": {
            "--agent": "Required recipient agent name.",
            "<message-id>": "Required message id.",
            "--note": "Optional handled note.",
        },
    },
    "sent": {
        "purpose": "List messages sent by an agent.",
        "parameters": {
            "--agent": "Required sender agent name.",
            "--all": "Include all history instead of the latest 20 messages.",
        },
    },
    "lint": {
        "purpose": "Validate the local notification queue and registry.",
        "parameters": {},
    },
    "watch run": {
        "purpose": "Run the watcher in the foreground.",
        "parameters": {
            "--agents": "Optional comma-separated agent names to monitor. Omit to monitor all watchable registered agents.",
            "--interval": "Polling interval in seconds. Default: 5.",
            "--timeout": "Per resume command timeout in seconds. Default: 1800.",
            "--once": "Run one scan and exit.",
        },
    },
    "watch install": {
        "purpose": "Install the watcher as a platform user background service.",
        "parameters": {
            "--agents": "Optional comma-separated agent names to monitor.",
            "--interval": "Polling interval in seconds. Default: 5.",
            "--timeout": "Per resume command timeout in seconds. Default: 1800.",
        },
    },
    "watch status": {
        "purpose": "Report watcher background service status for the current platform.",
        "parameters": {},
    },
    "watch uninstall": {
        "purpose": "Remove the watcher background service for the current platform.",
        "parameters": {},
    },
}
AGENT_RULES_TEXT = """# Agent Notify Rules

- Use `agent-notify` for all cross-agent notifications.
- Register local identities before use: `agent-notify register <agent> --type <codex|claude|reasonix>`.
- Register a single global main-agent first: `agent-notify register <agent> --type <codex|claude|reasonix> --main`.
- Non-main agents can only be registered after the main-agent exists. Switch the main-agent with `agent-notify set-main <agent>`.
- Agent names are inbox addresses; agent types select the wakeup driver.
- Check notifications at task start: `agent-notify inbox --agent <agent>` and `agent-notify lint`.
- Do not directly edit `.agent-notify/messages`, `.agent-notify/archive`, `.agent-notify/agents.json`, or watcher lock/state files.
- `send` only queues a notification; it does not prove the recipient was resumed or processed the message.
- Use `read --agent <agent> <message-id>` before acting on a notification.
- Use `handle --agent <agent> <message-id> --note <note>` only when the notification no longer needs follow-up.
- `handled` means notification follow-up is complete; it does not mean the underlying implementation task succeeded.
- When replying, start the body with `In reply to <message-id>` and include `--source-session-id <current-session-id>` when known.
- The background watcher is the only automatic wakeup path. Install it explicitly with `agent-notify watch install`.
- Messages sent to the main-agent itself only trigger a local system notification on supported platforms; they do not auto-resume that agent.
"""
REQUIRED_FIELDS = {
    "id",
    "from",
    "to",
    "status",
    "sequence",
    "subject",
    "body",
    "created_at",
    "updated_at",
    "read_at",
    "handled_at",
    "handled_note",
}
