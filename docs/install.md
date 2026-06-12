# Install

## 推荐方式：嵌入到目标项目的 `tools/agent_mail/`

假设你的目标项目根目录是：

```text
/path/to/your-project
```

推荐把 `agent-notify` 放成下面这种结构：

```text
/path/to/your-project/
├── tools/
│   └── agent_mail/
│       ├── agent_mail/
│       ├── cli.py
│       ├── docs/
│       └── README.md
```

### 1. 复制文件到目标项目

把独立仓库里的这些内容复制到目标项目的 `tools/agent_mail/` 目录下：

```text
agent_mail/
cli.py
docs/
README.md
```

复制完成后，目标项目里应当是：

```text
/path/to/your-project/
├── tools/
│   └── agent_mail/
│       ├── agent_mail/
│       ├── cli.py
│       ├── docs/
│       └── README.md
```

### 2. 切到目标项目根目录

后续命令都在目标项目根目录执行，不是在 `tools/agent_mail/` 子目录执行：

```bash
cd /path/to/your-project
```

### 3. 初始化目标项目

在目标项目根目录执行：

```bash
python3 tools/agent_mail/cli.py init
```

如果你希望进入目标项目目录时自动能用 `agent-notify`，则执行：

```bash
python3 tools/agent_mail/cli.py init --setup-direnv
```

### 4. 注册 agent

第一次注册必须在目标项目根目录执行，并且必须带 `--main`：

```bash
agent-notify register codex-main --type codex --main
```

然后再注册其他 agent：

```bash
agent-notify register claude-reviewer --type claude
agent-notify register reasonix-web --type reasonix
```

### 5. 验证目标项目中的安装

仍然在目标项目根目录执行：

```bash
agent-notify lint
```

如果你把测试也一起复制到了目标项目的 `tools/agent_mail/tests/`，再执行：

```bash
python3 -m unittest tools/agent_mail/tests/test_agent_mail.py
```

### 6. 后续更新

以后如果你替换或更新了 `tools/agent_mail/`，在目标项目根目录执行：

```bash
agent-notify update
```

这条命令会刷新本地入口和 `direnv` 授权。如果后台 watcher 已经安装，它会自动卸载并用原来的 watcher 参数重新安装。

如果只想更新入口，不想动 watcher：

```bash
agent-notify update --no-watch
```

如果系统后台启动项里有历史残留，先预览再清理：

```bash
agent-notify watch cleanup --dry-run
agent-notify watch cleanup
```

`cleanup` 只删除项目目录或启动入口已经不存在的失效 watcher；其他仍有效项目的 watcher 会保留。

## 次要方式：直接使用独立仓库

假设你已经把这个仓库克隆到本地，例如：

```text
/path/to/agent_mail
```

下面所有命令都在这个仓库根目录执行：

```bash
cd /path/to/agent_mail
```

### 1. 基本要求

- 已安装 Python 3
- 当前目录是一个 Git 工作目录
- 可选：安装 `direnv`，这样进入项目目录时可以自动得到 `agent-notify` 命令

### 2. 初始化本地运行态

在仓库根目录执行：

```bash
python3 cli.py init
```

这一步会在当前仓库根目录创建或更新：

- `.agent-notify/`
- `.gitignore`
- `.envrc`
- `bin/agent-notify`
- `bin/agent-notify.cmd`
- `bin/agent-notify.ps1`

### 3. 如果你想进入目录后自动能用 `agent-notify`

仍然在仓库根目录执行：

```bash
python3 cli.py init --setup-direnv
```

如果你已经执行过 `init`，也可以单独执行：

```bash
python3 cli.py setup-direnv
```

成功后，重新进入这个仓库目录，`agent-notify` 就会通过 `bin/` 出现在 `PATH` 中。

### 4. 注册 agent

第一次注册必须在仓库根目录执行，并且必须注册 main-agent：

```bash
agent-notify register codex-main --type codex --main
```

然后再注册其他 agent：

```bash
agent-notify register claude-reviewer --type claude
agent-notify register reasonix-web --type reasonix
```

### 5. 验证

仍然在仓库根目录执行：

```bash
agent-notify lint
python3 -m unittest tests/test_agent_mail.py
```

### 6. 后续更新

维护独立仓库本身时，更新代码后在仓库根目录执行：

```bash
agent-notify update
```

如需清理历史残留 watcher，先执行：

```bash
agent-notify watch cleanup --dry-run
```

## 平台说明

- macOS：`init --setup-direnv` 会通过 Homebrew 安装并接通 `direnv`
- Windows：`init --setup-direnv` 会通过 `winget` 安装并接通 `direnv`
- 发给 main-agent 本人的消息不会自动 resume 该 agent；在 macOS 和 Windows 上会改为本地系统通知
