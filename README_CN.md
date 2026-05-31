# TradingAgents 本地配置指南（Claude Max 路由版）

把 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 跑在本机，
LLM 推理全部走你的 **Claude Max 订阅**，不用 Anthropic 按量 API key。

---

## 一、它是怎么工作的

```
┌────────────────────┐    OpenAI-compatible HTTP    ┌────────────────────────┐
│   TradingAgents    │ ───────────────────────────► │ openclaw-claude-proxy  │
│ (LangChain/Graph)  │       127.0.0.1:3456         │   (Node 本地服务)      │
└────────────────────┘                              └────────┬───────────────┘
                                                             │ spawn 子进程
                                                             ▼
                                                    ┌────────────────────┐
                                                    │  claude (Code CLI) │
                                                    │  ── OAuth 已登录 ── │
                                                    └────────┬───────────┘
                                                             ▼
                                                    api.anthropic.com
                                                    （Max 订阅额度）
```

关键点：
- **proxy 不抠 OAuth token**，它只是以子进程方式调用 `claude` CLI，让官方 CLI 自己处理认证。
- TradingAgents 把 proxy 当作一个 OpenAI 兼容的网关（`provider=openrouter` + 自定义 `base_url`）。
- Claude CLI 用的是你本机已经登录的 Max 账号，所以费用走订阅而不是按量 API。

---

## 二、一次性环境准备（本机已完成）

### 1. 仓库与依赖
```powershell
git clone https://github.com/TauricResearch/TradingAgents.git `
  c:\Users\HP\Desktop\Agent\TradingAgents
cd c:\Users\HP\Desktop\Agent\TradingAgents
C:\Python313\python.exe -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. Claude Code CLI 与 proxy
```powershell
# 已安装：claude 2.1.146
npm install -g @anthropic-ai/claude-code   # 如果还没装
claude /login                              # 首次登录 Max 账号

npm install -g openclaw-claude-proxy
```

### 3. Windows 必做：让 Node spawn 找到 claude.exe
proxy 用 `spawn("claude", ...)` 启动子进程，Windows 默认 PATH 里只有 `claude.cmd`，
而 Node 自 CVE-2024-27980 起拒绝 spawn `.cmd`。复制官方 `.exe` 到 npm bin 目录即可：
```powershell
Copy-Item "$env:AppData\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe" `
          "$env:AppData\npm\claude.exe"
```
PATHEXT 默认 `.EXE` 在 `.CMD` 之前，proxy 会自动走 `.exe`。
**Claude Code 升级后如果不工作，重跑这一行。**

### 4. `.env`（已生成在仓库根目录）
关键字段：
```dotenv
TRADINGAGENTS_LLM_PROVIDER=openrouter
TRADINGAGENTS_LLM_BACKEND_URL=http://127.0.0.1:3456/v1
TRADINGAGENTS_DEEP_THINK_LLM=claude-opus-4-7
TRADINGAGENTS_QUICK_THINK_LLM=claude-haiku-4-5-20251001
OPENROUTER_API_KEY=sk-claude-proxy-local   # 占位，proxy 默认不校验
TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese
```

---

## 三、日常运行

开两个终端。

**终端 A：起 proxy（保持开着）**
```powershell
claude-proxy
```
默认绑定 `127.0.0.1:3456`，`Ctrl+C` 关闭。

**终端 B：跑分析**
```powershell
cd c:\Users\HP\Desktop\Agent\TradingAgents
.\.venv\Scripts\Activate.ps1

# 方式 A — 交互式 CLI（选股票、选分析师、选日期）
tradingagents --checkpoint

# 方式 B — 用 main.py 默认分析 NVDA 2024-05-10
python main.py
```

### 验证链路活着
```powershell
curl http://127.0.0.1:3456/health        # 应返回 status=ok + claude_cli_version
curl http://127.0.0.1:3456/v1/models     # 应列出 claude-opus-4-7 等
.\.venv\Scripts\python.exe smoke_test.py # 应打印: LLM response: TRADINGAGENTS_PROXY_OK
```

---

## 四、配置调优

### 控成本 / 配额
Opus 烧 Max 配额最快。常规跑用 Sonnet 即可：
```dotenv
TRADINGAGENTS_DEEP_THINK_LLM=claude-sonnet-4-6
TRADINGAGENTS_QUICK_THINK_LLM=claude-haiku-4-5-20251001
```

辩论 / 风险讨论轮数（每多一轮，深思层 token 翻倍）：
```dotenv
TRADINGAGENTS_MAX_DEBATE_ROUNDS=1
TRADINGAGENTS_MAX_RISK_ROUNDS=1
```

### 输出语言
内部 agent 辩论始终是英文（推理质量优先），最终报告语言：
```dotenv
TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese
```

### 数据源
默认 `yfinance`，免费、无需 key。
想换 Alpha Vantage：先去 [alphavantage.co](https://www.alphavantage.co/support/#api-key) 拿 key，
然后 `.env` 加：
```dotenv
ALPHA_VANTAGE_API_KEY=...
```
并把 `tradingagents/default_config.py` 里 `data_vendors` 改成 `alpha_vantage`。

---

## 五、故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `claude-proxy` 启动后 `/health` 显示 `spawn claude ENOENT` | Windows 上 Node 无法 spawn `.cmd` | 重跑上面的 `claude.exe` 复制命令 |
| `Port 3456 is already in use` | 之前的 proxy 没退干净 | `Get-NetTCPConnection -LocalPort 3456` 查 PID，`Stop-Process -Id <pid> -Force` |
| TradingAgents 报 `API key for provider 'openrouter' is not set` | 没读到 `.env` | 确认 `.env` 在仓库根目录，且没用 `python -c` 直跑（CLI 用 cwd 找 .env） |
| 跑到一半 `429` / `rate limit` | Max 周配额触顶 | 切 Sonnet/Haiku，或暂停几小时再跑 |
| `curl` 没返回，proxy 也没日志 | 端口被防火墙拦了 | proxy 默认只绑 loopback，本机应该没问题；如确实需要远程访问见 proxy 文档 |
| 模型名错被拒 | proxy 的模型列表跟 CLI 对齐 | `curl http://127.0.0.1:3456/v1/models` 看支持哪些 ID |

---

## 六、风险与合规提示

- **ToS 灰色地带**：Anthropic 没有正式开放 Max 订阅作为第三方 API 的入口。`openclaw-claude-proxy`
  走的是"headless Claude Code"路径（不抓 token、不绕认证），比直接 token 重放安全得多，
  但仍不等同于正式 API 合约。Anthropic 有权对异常使用模式做限流甚至封号。
- **个人研究 OK，商业转售不要**：Max 订阅协议明确禁止把订阅本身作为商品/服务提供给他人。
  TradingAgents 跑出来的策略你自己看、自己用没问题，做成服务卖给别人就过线了。
- **不要把 proxy 暴露到公网**：默认绑 `127.0.0.1` 就是这个目的。任何对外暴露都会让别人
  借你的 Max 配额薅羊毛，也会大大增加被 Anthropic 风控注意到的概率。
- **保留逃生路径**：留意 `console.anthropic.com` 的官方 API key 作为后备。如果 Max 路径
  被风控影响业务，可以直接把 `.env` 切到 `TRADINGAGENTS_LLM_PROVIDER=anthropic` +
  `ANTHROPIC_API_KEY=...`，零改动切换到按量计费。

---

## 七、目录结构

```
c:\Users\HP\Desktop\Agent\
├── TradingAgents\               # 本仓库（已 git clone）
│   ├── .env                     # 路由配置（Claude Max via proxy）
│   ├── .venv\                   # Python 依赖隔离环境
│   ├── tradingagents\           # 核心 agent / dataflows / LLM clients
│   ├── cli\                     # 交互式 CLI 入口
│   ├── main.py                  # 程序化入口
│   ├── smoke_test.py            # 端到端验通脚本
│   ├── RUN_LOCAL.md             # 英文速记版（同等信息）
│   └── README_CN.md             # 本文件
└── claude-proxy\                # mehdic/claude-proxy 源码（参考用）
                                  # 实际跑的是 npm 全局安装版
```

---

## 八、参考链接

- TradingAgents：<https://github.com/TauricResearch/TradingAgents>
- TradingAgents 论文：<https://arxiv.org/abs/2412.20138>
- openclaw-claude-proxy：<https://github.com/mehdic/claude-proxy>
- Claude Code CLI：<https://docs.anthropic.com/claude-code>
- Anthropic Max 订阅条款：<https://www.anthropic.com/legal/consumer-terms>
