# Agent Notify

`agent-notify` 是一个可复制到任意 Git 项目的本地 agent 协作通知单元。它解决的问题不是“模型怎么写代码”，而是“多个 agent 怎么可靠地互相发消息、知道谁该处理、在安全时唤醒已有会话”。

这个仓库就是完整可复用块：

```text
agent_mail/
├── README.md
├── cli.py
├── docs/
│   ├── agent-rules.md
│   └── cli-reference.md
└── tests/
    └── test_agent_mail.py
```

下文默认使用 `agent-notify ...`。如果目标项目不想用本地入口，也可以直接运行：

```bash
python3 cli.py ...
```

## 思想

这套机制刻意把三件事分开：

- **通知队列**：`send` 只把消息写入 `.agent-notify/`，不代表接收方已经处理。
- **agent 身份**：agent name 是收件箱地址，例如 `claude-reviewer`、`reasonix-web`、`codex-main`。
- **唤醒类型**：agent type 决定 watcher 用哪个 CLI 对接，目前是 `claude`、`reasonix`、`codex`。

所以一个 agent 注册时要同时说明 name 和 type：

```bash
agent-notify register claude-reviewer --type claude
agent-notify register reasonix-web --type reasonix
agent-notify register codex-main --type codex
```

发送消息时只使用 name：

```bash
agent-notify send --from codex-main --to claude-reviewer --subject "Review" --body "Please review."
```

watcher 再根据接收方的 type 决定调用 `claude`、`reasonix` 还是 `codex`。

## 重要接口

模型可以先调用内置 help 来了解工具：

```bash
agent-notify help
agent-notify help send
agent-notify help "watch run"
agent-notify help setup-direnv
```

关键接口：

```bash
agent-notify init
agent-notify setup-direnv
agent-notify register <agent-name> --type <codex|claude|reasonix>
agent-notify agents --details
agent-notify send --from <sender> --to <recipient> --subject <subject> --body <body>
agent-notify inbox --agent <agent>
agent-notify read --agent <agent> <message-id>
agent-notify handle --agent <agent> <message-id> --note <note>
agent-notify sent --agent <agent>
agent-notify lint
agent-notify watch install --agents <agent-name>,<agent-name>
agent-notify watch status
agent-notify watch run --once --agents <agent-name>
```

完整接口、参数、输出字段和失败语义在：

```text
docs/cli-reference.md
```

可复制到项目规则文档的规则块在：

```text
docs/agent-rules.md
```

## 接入一个项目

1. 复制整个目录：

```text
agent_mail/  (package)
cli.py
docs/
tests/
README.md
```

2. `init` 会自动生成本地入口。如果目标项目想手动准备，也可以添加同名入口：

```python
#!/usr/bin/env python3
"""Compatibility entry point for the bundled agent-notify tool."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "cli.py"
    runpy.run_path(str(target), run_name="__main__")
```

保存为仓库根目录下的 `bin/agent-notify`。Windows 项目还应同时生成 `bin/agent-notify.cmd` 和 `bin/agent-notify.ps1`：

```text
bin/agent-notify
```

3. 初始化项目：

```bash
agent-notify init
```

`init` 只做项目级初始化：

- 创建 `.agent-notify/` 运行目录。
- 确保 `.gitignore` 包含 `.agent-notify/`。
- 如果仓库根目录还没有 `.envrc`，写入 `PATH_add bin`。
- 如果仓库根目录还没有本地入口，写入 `bin/agent-notify`、`bin/agent-notify.cmd`、`bin/agent-notify.ps1`。
- 如果本机安装了 `direnv`，会立刻对这份新生成的 `.envrc` 执行 `direnv allow`。
- 如果传入 `--setup-direnv`，会先按当前平台接通 `direnv` 再执行 `allow`。
- 默认不注册 agent。
- 默认不安装 watcher。

如果仓库里本来就已经有 `.envrc`，`init` 不会覆盖它，也不会自动替它执行 `direnv allow`。这种情况仍然需要你自己决定是否授权。

如果本机没安装 `direnv`，推荐直接运行：

```bash
agent-notify setup-direnv
```

或者初始化时一起做：

```bash
agent-notify init --setup-direnv
```

在交互终端里，`init` 遇到未安装的 `direnv` 也会询问是否现在安装并接通。

如果你选择手动安装 `direnv`，则在安装后执行一次：

```bash
direnv allow
```

之后每次进入该项目目录，`agent-notify` 都会自动出现在 `PATH` 中。

### `setup-direnv` 平台范围

- macOS：安装 `direnv`，并把 `eval "$(direnv hook zsh)"` 写入 `~/.zshrc`
- Windows：安装 `direnv`，并把 `Invoke-Expression "$(direnv hook pwsh)"` 写入 PowerShell 当前用户 profile

查看当前状态：

```bash
agent-notify setup-direnv --status
```

4. 注册实际 agent：

```bash
agent-notify register codex-main --type codex
agent-notify register claude-reviewer --type claude
agent-notify register reasonix-web --type reasonix
```

5. 需要自动唤醒时安装 watcher：

```bash
agent-notify watch install --agents claude-reviewer,reasonix-web
```

`watch install` 会按当前平台安装后台 watcher：

- macOS：使用 `launchd`
- Windows：使用 Task Scheduler

如果当前平台不支持后台安装，仍然可以用前台方式：

```powershell
agent-notify watch run --agents claude-reviewer,reasonix-web --interval 5
```

## Agent 如何配合

每个 agent 在任务开始时应做：

```bash
agent-notify inbox --agent <agent-name>
agent-notify lint
```

收到通知后：

```bash
agent-notify read --agent <agent-name> <message-id>
```

如果需要回复，正文开头必须是：

```text
In reply to <message-id>
```

发送方知道当前会话时应带：

```bash
--source-session-id <session-id>
```

处理完并且必要回复已经发送成功后，才标记 handled：

```bash
agent-notify handle --agent <agent-name> <message-id> --note "Done."
```

`handled` 只表示这条通知不再需要跟进，不表示通知里的开发任务成功完成。

## 如何更新项目规则文档

把下面文件里的规则块复制到目标项目的 `AGENTS.md`、`CLAUDE.md` 或等价规则文件：

```text
docs/agent-rules.md
```

最少要写清楚：

- 新通知必须用 `agent-notify`。
- `.agent-notify/` 是本地运行态，必须进 `.gitignore`。
- agent 必须注册 name 和 type。
- 禁止直接编辑 `.agent-notify/` 内部文件。
- `send` 只表示 queued，不表示接收方已处理。
- `handled` 只关闭通知生命周期，不代表实现任务完成。
- watcher 是自动唤醒入口；不能安全 resume 时消息保持 unread。

也可以让工具直接输出规则块：

```bash
agent-notify init --print-agent-rules
```

## 验证

```bash
python3 -m unittest tests/test_agent_mail.py
agent-notify lint
```
