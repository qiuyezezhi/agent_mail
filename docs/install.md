# Install

## Requirements

- Python 3
- Git repository working tree
- Optional: `direnv` for automatic `agent-notify` activation when entering the project directory

## Quick Start

1. Put these files into your project:

```text
agent_mail/
cli.py
docs/
README.md
```

2. Initialize the repository-local runtime:

```bash
python3 cli.py init
```

3. If you want automatic command activation when entering the project directory:

```bash
python3 cli.py init --setup-direnv
```

4. Register the first agent as the single main-agent:

```bash
agent-notify register codex-main --type codex --main
```

5. Register any additional agents:

```bash
agent-notify register claude-reviewer --type claude
agent-notify register reasonix-web --type reasonix
```

6. Verify the local runtime:

```bash
agent-notify lint
python3 -m unittest tests/test_agent_mail.py
```

## Platform Notes

- macOS: `init --setup-direnv` can install and hook `direnv` via Homebrew.
- Windows: `init --setup-direnv` can install and hook `direnv` via `winget`, and the watcher can use Task Scheduler.
- Messages sent to the main-agent itself do not auto-resume that agent. On macOS and Windows they produce a local system notification instead.
