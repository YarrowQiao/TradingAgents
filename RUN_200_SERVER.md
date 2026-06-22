# TradingAgents 在 200 服务器（`gpu-test-01`，10.40.0.200）上的运行说明 — Linux 版

[RUN_LOCAL.md](RUN_LOCAL.md)（Windows/PowerShell 版）的 Linux/bash 对应版本。
架构相同：TradingAgents 通过本地回环（loopback）访问 **claude-proxy**，该代理封装了已认证的
`claude` CLI，并以 OpenAI 兼容 API 的形式暴露在 `http://127.0.0.1:3456` 上。
推理费用由你的 Claude 订阅承担。

```
TradingAgents  ──HTTP──▶  claude-proxy (127.0.0.1:3456)  ──spawn──▶  claude CLI  ──▶  Claude
```

## 主机现状（本机已配置完成）

- 代码仓库：`/mnt/allin_data/model_file/group/qyc/TradingAgents`
- Python 虚拟环境：仓库内的 `.venv`（Python 3.10.12），依赖通过 `pip install -e .` 安装
- Node：通过 nvm 安装的 v20.20.2（`/home/qyc/.nvm/versions/node/v20.20.2/bin`）
- `claude` CLI：已在 PATH 中（`which claude`）
- claude-proxy：**已内置于仓库中**，位于 `claude-proxy/dist/`（已编译好——无需全局 npm 安装）
- `.env`：已预先配置好指向本地代理，详见 [.env](.env)

> Windows 上的 `.exe`/`.cmd` spawn 兼容补丁在这里不适用——Linux 上 `spawn("claude", …)` 能正常解析。

## ⚠️ 公司代理的坑（本机最容易导致运行失败的第一原因）

本机设置了 `http_proxy`/`https_proxy`。OpenAI 客户端会把 `127.0.0.1:3456` 的请求
**经由**公司代理转发，从而返回 503。`127.0.0.1` 必须保留在 `NO_PROXY` 中。
这一点已在 [.env](.env) 中处理好（`NO_PROXY` / `no_proxy` 都已设置），但如果你在 shell 中
导出了代理变量，请务必把回环地址排除掉：

```bash
export NO_PROXY=localhost,127.0.0.1,.local,.allintechinc.com
export no_proxy=$NO_PROXY
```

## 如何运行一次分析

需要两个终端（或两个 tmux 面板——推荐，这样代理在断开连接后仍能存活）。

**终端 A —— 代理**（保持开启；按 `Ctrl+C` 停止）：

```bash
cd /mnt/allin_data/model_file/group/qyc/TradingAgents
node claude-proxy/dist/server/standalone.js
# 默认端口 3456；可通过以下方式覆盖：  node claude-proxy/dist/server/standalone.js 3456
# 或：  CLAUDE_PROXY_PORT=3456 node claude-proxy/dist/server/standalone.js
```

首次启动时会校验 `claude` CLI 和认证状态。如果打印出认证错误，先交互式运行一次
`claude` 完成登录，然后重启代理。

**终端 B —— TradingAgents：**

```bash
cd /mnt/allin_data/model_file/group/qyc/TradingAgents
source .venv/bin/activate          # ← Linux 下等价于 .\.venv\Scripts\Activate.ps1

# 交互式 CLI（股票代码选择、分析师开关等）
tradingagents

# 或者：以脚本方式运行
python main.py
```

报告会写入 `reports/<TICKER>_<时间戳>/`。

## 验证链路是否打通

```bash
# 代理是否存活？
curl http://127.0.0.1:3456/health

# 暴露了哪些模型？
curl http://127.0.0.1:3456/v1/models

# 端到端：LangChain → 代理 → claude CLI → Claude
.venv/bin/python smoke_test.py
# 期望最后一行：  LLM response: TRADINGAGENTS_PROXY_OK
```

如果 `curl` 本身卡住或返回 503，请重新检查上面的 NO_PROXY 说明。

## 模型 / 成本调节项（来自 [.env](.env)）

| 角色 | 环境变量 | 当前取值 |
|------|---------|---------------|
| 深度思考 | `TRADINGAGENTS_DEEP_THINK_LLM` | `claude-opus-4-8` |
| 快速思考 | `TRADINGAGENTS_QUICK_THINK_LLM` | `claude-haiku-4-5-20251001` |
| 提供方 | `TRADINGAGENTS_LLM_PROVIDER` | `openrouter`（OpenAI 兼容客户端，已覆盖 base URL） |
| 后端地址 | `TRADINGAGENTS_LLM_BACKEND_URL` | `http://127.0.0.1:3456/v1` |

模型 ID 必须是代理实际暴露的——请以 `GET /v1/models` 的返回为准。
Opus 消耗配额很快；日常运行可把深度模型换成 Sonnet：

```bash
TRADINGAGENTS_DEEP_THINK_LLM=claude-sonnet-4-6
```

辩论 / 风险讨论轮数（每多一轮，该阶段的深度思考 token 消耗大致翻倍）：

```bash
TRADINGAGENTS_MAX_DEBATE_ROUNDS=1
TRADINGAGENTS_MAX_RISK_ROUNDS=1
```

## 无人值守运行（可选）

让代理在 SSH 断开后仍保持运行：

```bash
# tmux
tmux new -s claude-proxy 'cd /mnt/allin_data/model_file/group/qyc/TradingAgents && node claude-proxy/dist/server/standalone.js'
# 脱离会话：Ctrl+b d   |   重新接入：tmux attach -t claude-proxy

# 或者用 nohup
cd /mnt/allin_data/model_file/group/qyc/TradingAgents
nohup node claude-proxy/dist/server/standalone.js > proxy.log 2>&1 &
```

## 故障排查

- **`..venvScriptsActivate.ps1: command not found`** —— 那是 Windows 路径；Linux 上请用 `source .venv/bin/activate`。
- **连接 127.0.0.1:3456 时 `Connection refused`** —— 代理没运行（终端 A）或端口不对。
- **代理返回 `503`** —— 公司代理吞掉了回环请求；修正 `NO_PROXY`（见上文）。
- **终端 A 里 `node: command not found`** —— 该 shell 没加载 nvm；运行 `source ~/.nvm/nvm.sh` 或新开一个登录 shell。
- **代理启动时报认证错误** —— 先运行一次 `claude` 完成认证，然后重启代理。
