# Agent Notify CLI API Reference

这是 `agent-notify` 的接口文档。Agent 使用这份文档理解命令、参数、输出和失败语义，不需要阅读脚本源码。

## 核心概念

| 概念 | 含义 |
| --- | --- |
| Agent name | 收件箱地址，用在 `send --to`、`inbox --agent`、`read --agent`、`handle --agent`、`watch --agents` |
| Agent type | 唤醒驱动，目前支持 `codex`、`claude`、`reasonix` |
| Main-agent | 全局唯一主 agent。必须先注册，且发给它本人的通知只做本地系统提醒，不自动 resume |
| Message | `.agent-notify/messages/*.json` 中的一条通知 |
| Watcher | 后台轮询 unread 消息，并在安全时 resume 对应 agent session |

`send` 只表示消息入队，不表示接收 agent 已经被唤醒、读取或处理。

## 命令总表

| 命令 | 作用 |
| --- | --- |
| `help` | 输出工具作用、接口列表和单接口参数说明 |
| `init` | 初始化当前 Git 仓库的通知机制 |
| `update` | 更新本地入口并在 watcher 已安装时自动重启 watcher |
| `register` | 注册一个 agent name，并绑定 agent type |
| `agents` | 查看已注册 agent |
| `set-main` | 切换全局唯一 main-agent |
| `send` | 发送通知到收件箱 |
| `inbox` | 查看某个 agent 的收件箱 |
| `read` | 读取通知，并把 `unread` 改成 `read` |
| `handle` | 标记通知已处理，并归档 |
| `sent` | 查看某个 agent 发出的通知 |
| `lint` | 校验本地通知队列结构 |
| `setup-direnv` | 安装并接通 `direnv` |
| `watch run` | 前台运行 watcher |
| `watch install` | 安装当前平台的后台 watcher |
| `watch status` | 查看 watcher 安装/加载状态 |
| `watch uninstall` | 卸载 watcher |
| `watch cleanup` | 清理明显失效的 watcher 残留 |

## 通用输出和失败语义

| 项 | 规则 |
| --- | --- |
| 成功 | stdout 输出 JSON，exit code 为 `0` |
| 失败 | stderr 输出错误文本，exit code 非 `0` |
| JSON 解析 | 只有 exit code 为 `0` 时才应解析 stdout |
| 本地状态 | `.agent-notify/` 是运行态目录，必须忽略并禁止直接编辑 |

## Runtime 目录

```text
.agent-notify/
├── agents.json
├── state.json
├── watcher-state.json
├── lock.d/
├── watcher-locks/
├── logs/
│   └── watcher.log
├── messages/
└── archive/
```

## Message JSON

```json
{
  "id": "32-hex-character-id",
  "from": "sender-agent-name",
  "to": "recipient-agent-name",
  "status": "unread",
  "sequence": 1,
  "subject": "subject text",
  "body": "message body",
  "source_session_id": "optional sender session id",
  "created_at": "2026-06-11T12:00:00.000000+08:00",
  "updated_at": "2026-06-11T12:00:00.000000+08:00",
  "read_at": null,
  "handled_at": null,
  "handled_note": null
}
```

| Status | 含义 |
| --- | --- |
| `unread` | 接收方尚未通过 `read` 打开 |
| `read` | 接收方已读取，但可能还需要处理 |
| `handled` | 通知生命周期结束，消息已归档 |

`handled` 只表示这条通知不再需要跟进，不表示通知里的实现任务成功完成。

## `help`

让 agent 通过 CLI 自发现工具作用、接口列表和参数。

```bash
agent-notify help [topic]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `[topic]` | 否 | 接口名，例如 `send`、`init`、`watch run` |

示例：

```bash
agent-notify help
agent-notify help send
agent-notify help "watch run"
```

输出：

- 不传 topic 时返回工具目的、关键规则、接口列表和文档路径。
- 传 topic 时返回该接口的 `purpose`、`parameters` 和文档路径。

失败：

| 情况 | 结果 |
| --- | --- |
| topic 不存在 | 非 0，报 `unknown help topic` |

## `init`

初始化当前 Git 仓库的通知机制。

```bash
agent-notify init [options]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--agents <csv>` | 否 | 初始化时顺便注册 agent，格式 `name:type,name:type` |
| `--no-gitignore` | 否 | 不维护 `.gitignore` |
| `--install-watcher` | 否 | 初始化后安装 watcher |
| `--watch-agents <csv>` | 否 | 高级过滤项；配合 `--install-watcher` 覆盖默认监控范围；main-agent 只通知不唤醒 |
| `--interval <seconds>` | 否 | watcher 轮询间隔，默认 `5` |
| `--timeout <seconds>` | 否 | 单次 resume 命令超时，默认 `1800` |
| `--setup-direnv` | 否 | 先为当前平台安装并接通 `direnv`，再继续初始化 |
| `--print-agent-rules` | 否 | 在 JSON 输出中附带可复制到 `AGENTS.md` 的规则块 |

行为：

- 创建 `.agent-notify/` 目录结构。
- 默认只确保 `.gitignore` 包含 `.agent-notify/`。
- 如果仓库根目录还没有 `.envrc`，写入 `PATH_add bin`。
- 如果仓库根目录还没有本地入口，写入 `bin/agent-notify`、`bin/agent-notify.cmd`、`bin/agent-notify.ps1`。
- 如果本机安装了 `direnv`，会立即对这份新生成的 `.envrc` 执行 `direnv allow`。
- 如果传入 `--setup-direnv`，会先安装并接通 `direnv`，再执行 `direnv allow`。
- 默认不注册 agent。
- 如果传入 `--agents`，首个新注册 agent 会自动成为 main-agent。
- 默认不安装 watcher。
- 重复运行不会重复追加 `.gitignore`。
- 已存在的 `.envrc` 不会被覆盖。
- 已存在的 `.envrc` 不会被自动 `allow`。
- 交互终端里如果还没安装 `direnv`，会询问是否现在安装并接通。

示例：

```bash
agent-notify init
agent-notify init --agents codex-main:codex,claude-reviewer:claude
agent-notify init --install-watcher
```

输出字段：

| 字段 | 含义 |
| --- | --- |
| `root` | `.agent-notify/` 绝对路径 |
| `gitignore` | `.gitignore` 路径，`--no-gitignore` 时为 `null` |
| `gitignore_updated` | 本次是否修改 `.gitignore` |
| `envrc` | `.envrc` 路径 |
| `envrc_updated` | 本次是否创建 `.envrc` |
| `entrypoint` | Unix 风格本地入口路径 |
| `entrypoints` | 本地入口集合，包含 `posix`、`cmd`、`powershell` |
| `direnv` | `direnv` 可用性与自动 allow 结果 |
| `direnv_setup` | `direnv` 安装/接通结果；未触发时为 `null` |
| `agents` | 已注册 agent name 列表 |
| `agent_details` | 已注册 agent 的 `{name,type,main}` 列表 |
| `registered_agents` | 本次新注册的 agent name |
| `watcher` | watcher 安装结果 |
| `next_steps` | 建议下一步命令 |
| `rules` | 仅 `--print-agent-rules` 时出现 |

## `update`

刷新项目本地入口和运行环境。用于 `tools/agent_mail/` 代码更新后，把当前项目的 `bin/agent-notify*` 和 watcher 更新到新版本。

```bash
agent-notify update [options]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--no-gitignore` | 否 | 不维护 `.gitignore` |
| `--no-direnv` | 否 | 跳过 `direnv allow` |
| `--no-watch` | 否 | 跳过 watcher 检查和重启 |
| `--watch-agents <csv>` | 否 | 高级过滤项；重装已安装 watcher 时覆盖默认 agent 列表 |
| `--interval <seconds>` | 否 | 重装已安装 watcher 时覆盖轮询间隔 |
| `--timeout <seconds>` | 否 | 重装已安装 watcher 时覆盖单次 resume 超时 |

行为：

- 确保 `.agent-notify/` 目录结构存在。
- 默认确保 `.gitignore` 包含 `.agent-notify/`。
- 如果仓库根目录还没有 `.envrc`，写入 `PATH_add bin`。
- 强制刷新本地入口：`bin/agent-notify`、`bin/agent-notify.cmd`、`bin/agent-notify.ps1`。
- 默认在本机有 `direnv` 时执行 `direnv allow <project-root>`。
- 默认检查 watcher 状态；如果 watcher 已安装，读取原有 `agents/interval/timeout` 并自动卸载后重装。
- 如果 watcher 没安装，不会自动安装新的 watcher。

示例：

```bash
agent-notify update
agent-notify update --no-watch
agent-notify update --interval 5
```

输出字段：

| 字段 | 含义 |
| --- | --- |
| `root` | `.agent-notify/` 绝对路径 |
| `gitignore_updated` | 本次是否修改 `.gitignore` |
| `envrc_updated` | 本次是否创建 `.envrc` |
| `entrypoint_updated` | 本次是否刷新本地入口 |
| `direnv` | `direnv allow` 结果 |
| `watcher` | watcher 检查、跳过或重装结果 |

## `setup-direnv`

为当前平台安装并接通 `direnv`。

```bash
agent-notify setup-direnv [--shell <zsh|pwsh>] [--status]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--shell <zsh|pwsh>` | 否 | 覆盖默认 shell。macOS 默认 `zsh`，Windows 默认 `pwsh` |
| `--status` | 否 | 只输出状态，不修改系统 |

平台行为：

- macOS：使用 `brew install direnv`，并把 `eval "$(direnv hook zsh)"` 写入 `~/.zshrc`
- Windows：使用 `winget install --id direnv.direnv -e`，并把 `Invoke-Expression "$(direnv hook pwsh)"` 写入 PowerShell 当前用户 profile

输出字段：

| 字段 | 含义 |
| --- | --- |
| `shell` | 目标 shell |
| `available` | 当前是否可找到 `direnv` |
| `executable` | `direnv` 可执行路径 |
| `installed_now` | 本次是否执行了安装 |
| `install_command` | 本次实际执行的安装命令 |
| `profile` | 被检查或写入的 shell profile |
| `hook_present` | hook 是否已存在 |
| `hook_added` | 本次是否追加了 hook |
| `restart_required` | 是否需要重开 shell 才能生效 |

状态模式额外字段：

| 字段 | 含义 |
| --- | --- |
| `profile_exists` | profile 文件是否存在 |
| `hook_line` | 期望存在的 hook 行 |

## `register`

注册 agent name，并绑定 agent type。

```bash
agent-notify register <agent-name> --type <codex|claude|reasonix> [--main]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `<agent-name>` | 是 | 收件箱名称 |
| `--type <type>` | 条件必需 | 唤醒驱动，支持 `codex`、`claude`、`reasonix` |
| `--main` | 否 | 把该 agent 设为全局唯一 main-agent |

兼容规则：

- `register codex` 推断为 `--type codex`
- `register claude` 推断为 `--type claude`
- `register reasonix` 推断为 `--type reasonix`
- 其他名称必须显式传 `--type`

示例：

```bash
agent-notify register codex-main --type codex --main
agent-notify register claude-reviewer --type claude
agent-notify register reasonix-web --type reasonix
```

约束：

- 第一个注册的 agent 必须使用 `--main`。
- main-agent 全局只能有一个。
- 自定义名称仍然必须显式传 `--type`。

失败：

| 情况 | 结果 |
| --- | --- |
| agent name 已存在 | 非 0，报 `agent already registered` |
| 第一个注册未带 `--main` | 非 0，报 `cannot register non-main agent before a main-agent exists` |
| 已存在 main-agent 还再次传 `--main` | 非 0，报 `main-agent already exists` |
| type 不支持 | 非 0，报 `unsupported agent type` |
| 自定义 name 缺少 type | 非 0，报 `agent type is required` |

## `agents`

查看已注册 agent。

```bash
agent-notify agents [--details]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--details` | 否 | 输出 `{name,type,main}` 详情 |

输出：

```json
["claude-reviewer", "codex-main"]
```

详情输出：

```json
[
  {"name": "claude-reviewer", "type": "claude", "main": false},
  {"name": "codex-main", "type": "codex", "main": true}
]
```

## `set-main`

切换全局唯一 main-agent 到一个已注册 agent。

```bash
agent-notify set-main <agent-name>
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `<agent-name>` | 是 | 已注册 agent 名称 |

示例：

```bash
agent-notify set-main claude-reviewer
```

输出：

```json
{
  "main_agent": "claude-reviewer",
  "updated": true
}
```

失败：

| 情况 | 结果 |
| --- | --- |
| agent 未注册 | 非 0，报 `unregistered agent` |
| 已经是 main-agent | 非 0，报 `agent is already the main-agent` |

## `send`

发送通知。

```bash
agent-notify send --from <sender> --to <recipient> --subject <subject> (--body <text>|--body-file <path|->)
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--from <agent>` | 是 | 发送方 agent name |
| `--to <agent>` | 是 | 接收方 agent name |
| `--subject <text>` | 是 | 通知标题 |
| `--body <text>` | 二选一 | 直接传正文 |
| `--body-file <path>` | 二选一 | 从文件读取正文 |
| `--body-file -` | 二选一 | 从 stdin 读取正文 |
| `--source-session-id <id>` | 否 | 发送方当前 session id，用于回复路由 |

输出：完整 Message JSON，初始状态为 `unread`。

失败：

| 情况 | 结果 |
| --- | --- |
| `--from` 未注册 | 非 0，报 `unregistered agent` |
| `--to` 未注册 | 非 0，报 `unregistered agent` |

## `inbox`

查看收件箱。

```bash
agent-notify inbox --agent <agent>
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--agent <agent>` | 是 | 接收方 agent name |

输出：message summary 列表，按新到旧排序。

## `read`

读取一条通知。

```bash
agent-notify read --agent <agent> <message-id>
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--agent <agent>` | 是 | 接收方 agent name |
| `<message-id>` | 是 | 消息 id |

行为：

- 如果状态是 `unread`，改成 `read`。
- 写入 `read_at`。
- 返回完整 Message JSON。

失败：

| 情况 | 结果 |
| --- | --- |
| 消息不存在 | 非 0 |
| 消息不是发给该 agent | 非 0 |

## `handle`

关闭通知生命周期并归档。

```bash
agent-notify handle --agent <agent> <message-id> [--note <note>]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--agent <agent>` | 是 | 接收方 agent name |
| `<message-id>` | 是 | 消息 id |
| `--note <note>` | 否 | 处理说明，写入 `handled_note` |

行为：

- 必要时补写 `read_at`。
- 设置 `status=handled`。
- 写入 `handled_at` 和 `handled_note`。
- 从 `messages/` 移动到 `archive/`。
- 清理该消息的 watcher retry 状态。

## `sent`

查看发件记录。

```bash
agent-notify sent --agent <agent> [--all]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--agent <agent>` | 是 | 发送方 agent name |
| `--all` | 否 | 输出全部历史；默认只输出最近 20 条 |

## `lint`

校验通知队列。

```bash
agent-notify lint
```

检查：

- JSON 是否合法。
- 必需字段是否存在。
- status 是否为 `unread/read/handled`。
- `from` / `to` 是否为已注册 agent。
- `handled` 消息是否已归档。

## `watch run`

前台运行 watcher。

```bash
agent-notify watch run [--agents <csv>] [--interval <seconds>] [--timeout <seconds>] [--once]
```

参数：

| 参数 | 必需 | 作用 |
| --- | --- | --- |
| `--agents <csv>` | 否 | 高级过滤项；省略时监控所有支持 watcher 的已注册 agent；main-agent 只通知不唤醒 |
| `--interval <seconds>` | 否 | 轮询间隔，默认 `5` |
| `--timeout <seconds>` | 否 | 单次 resume 超时，默认 `1800` |
| `--once` | 否 | 只扫描一轮，用于测试 |

行为：

- 每个 agent 每轮只取最早的 unread 消息。
- 按 agent type 调用对应唤醒驱动。
- 如果目标 agent 是 main-agent，watcher 不 resume；它只尝试发本地系统通知。
- 同一 agent/session 同时只允许一个 resume。
- resume 成功不代表消息 handled；接收 agent 必须自己 `read`、处理、`handle`。
- resume 失败、超时、找不到 session 时，消息保持 `unread`。

输出字段：

| 字段 | 含义 |
| --- | --- |
| `attempted` | 成功 resume 的消息列表 |
| `failed` | resume 失败或命令失败的消息列表 |
| `skipped` | 因无安全会话、退避、锁冲突等跳过的消息列表 |
| `notified` | 对 main-agent 仅发送本地系统通知的消息列表；macOS 会包含 `notifier` 字段表示 `helper-app` 或 `osascript` |

## `watch install`

安装后台 watcher。

```bash
agent-notify watch install [--agents <csv>] [--interval <seconds>] [--timeout <seconds>]
```

默认不需要 `--agents`；省略时 watcher 监控所有支持 watcher 的已注册 agent。非 main agent 会被自动唤醒；main-agent 只发本地系统通知。`--agents` 只作为高级过滤项使用。

平台行为：

- macOS：安装 `launchd` user agent
- Windows：安装 Task Scheduler `ONLOGON` 任务

macOS 系统通知优先使用隐藏后台 helper app，安装位置是 `~/Library/Application Support/agent-notify/notifier/agent-notify.app`。它不会出现在启动台、Dock 或 `/Applications`；如果缺少 Swift 编译器或 helper app 无法安装，会回退到 `osascript`。

输出字段：

| 字段 | 含义 |
| --- | --- |
| `installed` | 是否安装成功 |
| `loaded` | 后台服务是否已加载 |
| `label` | 平台 watcher 标识 |
| `plist` / `launcher` | 平台配置文件或启动脚本路径 |
| `log` | watcher 日志路径 |
| `scheduler` | 仅 Windows 出现，固定为 `taskschd` |

## `watch status`

查看 watcher 状态。

```bash
agent-notify watch status
```

输出：

| 字段 | 含义 |
| --- | --- |
| `installed` | 平台 watcher 配置是否存在 |
| `loaded` | 平台 watcher 是否已加载 |
| `label` | 平台 watcher 标识 |
| `plist` / `launcher` | 平台配置文件或启动脚本路径 |
| `log` | 日志路径 |
| `scheduler` | 仅 Windows 出现，固定为 `taskschd` |

## `watch uninstall`

卸载 watcher。

```bash
agent-notify watch uninstall
```

行为：

- macOS：`launchctl unload <plist>` 并删除 plist
- Windows：删除 Task Scheduler 任务并删除 launcher 脚本
- 不删除 `.agent-notify/` 队列

## `watch cleanup`

清理明显失效的 watcher 残留。

```bash
agent-notify watch cleanup [--dry-run]
```

行为：

- 默认只删除明显失效的 watcher，例如项目目录不存在、启动入口不存在、脚本不存在、或平台配置损坏。
- 不会因为 watcher 属于其他项目就删除；其他仍有效的项目会保留并出现在 `kept` 输出中。
- 不删除 `.agent-notify/` 队列，不清空通知。
- `--dry-run` 只报告将删除哪些项，不实际删除。

输出字段：

| 字段 | 含义 |
| --- | --- |
| `checked` | 是否执行了平台扫描 |
| `dry_run` | 是否只预览 |
| `removed` | 已删除或将删除的失效 watcher |
| `kept` | 保留的有效 watcher，包括其他项目 |

## Reply Routing

回复通知时，正文必须以这行开头：

```text
In reply to <message-id>
```

如果发送方知道当前 session，发送时应加：

```bash
--source-session-id <session-id>
```

watcher 会用这两个字段优先恢复原发送方 session。

## Watcher Driver Mapping

| Agent type | Session 发现 | Resume 命令 |
| --- | --- | --- |
| `claude` | `~/.claude/history.jsonl`、`~/.claude/sessions/*.json`、`~/.claude/projects/.../*.jsonl` | `claude -r <session-id> ... -p <prompt>` |
| `reasonix` | `~/Library/Application Support/reasonix/sessions/*.jsonl` | `reasonix run --resume <session-jsonl> <prompt>` |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl` 和 process manager | `codex exec resume <session-id> <prompt>` |
