# Agent Notify Rules Block

Copy this block into `AGENTS.md`, `CLAUDE.md`, or another project-level agent instruction file when enabling `agent-notify`.

```markdown
## Agent Notification Rules

- Use `agent-notify` for all cross-agent notifications.
- Initialize the repository once with `agent-notify init`.
- After updating `tools/agent_mail/`, run `agent-notify update` from the project root to refresh entry points and restart an installed watcher.
- When project-local command activation is desired, run `agent-notify setup-direnv` or `agent-notify init --setup-direnv`.
- Keep `.agent-notify/` in `.gitignore`; it is local runtime state and must not be committed.
- Do not directly edit `.agent-notify/messages`, `.agent-notify/archive`, `.agent-notify/agents.json`, `.agent-notify/watcher-state.json`, or lock paths.
- Register exactly one main-agent first with `agent-notify register <agent-name> --type <codex|claude|reasonix> --main`.
- Register other agent identities with `agent-notify register <agent-name> --type <codex|claude|reasonix>`.
- Switch the main-agent only through `agent-notify set-main <agent-name>`.
- Agent names are inbox addresses; agent types select the wakeup driver.
- At the start of each task, run `agent-notify inbox --agent <agent>` and `agent-notify lint`.
- Send notifications with `agent-notify send --from <sender> --to <recipient> --subject <subject> --body <body>` or `--body-file <path>`.
- Use `--source-session-id <session-id>` when the sender knows its current session.
- `send` only queues a notification. It does not prove the recipient was resumed, read the message, or completed the work.
- Read received notifications with `agent-notify read --agent <agent> <message-id>`.
- Mark notifications handled with `agent-notify handle --agent <agent> <message-id> --note <note>` only after required follow-up succeeds.
- `handled` only means the notification lifecycle is closed; it does not mean the underlying implementation task succeeded.
- Reply bodies must start with `In reply to <message-id>` so the watcher can route replies to the sender's original session when possible.
- The background watcher is the only automatic wakeup mechanism. Install it explicitly with `agent-notify watch install`; by default it monitors all non-main watchable agents.
- Messages addressed to the main-agent itself only trigger a local system notification on supported platforms; they do not auto-resume that agent session.
- If the watcher is not installed or cannot safely resume a session, messages remain queued until an agent handles them manually or a later watcher pass succeeds.
- Treat `.agent-notify/logs/watcher.log` as wakeup diagnostics, not as the authoritative task result.
```

After adding the rules, run:

```bash
agent-notify init
agent-notify setup-direnv
agent-notify lint
```
