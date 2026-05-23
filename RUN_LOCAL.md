# TradingAgents on Claude Max — local run notes

This setup routes TradingAgents through `openclaw-claude-proxy`, which wraps
the authenticated `claude` CLI and re-exposes it on `http://127.0.0.1:3456`
as an OpenAI-compatible HTTP API. TradingAgents talks to that loopback
endpoint and your Claude Max subscription pays for the inference.

## One-time setup (already done on this machine)

1. Repo: cloned at `c:\Users\HP\Desktop\Agent\TradingAgents`.
2. Python venv: `.venv` inside the repo, deps installed via `pip install -e .`.
3. Claude Code CLI: globally installed (`claude --version` → 2.1.146).
4. `openclaw-claude-proxy`: globally installed via `npm install -g openclaw-claude-proxy`.
5. Windows fix: copied `node_modules\@anthropic-ai\claude-code\bin\claude.exe`
   alongside `claude.cmd` in `%AppData%\npm\` so Node's `spawn("claude", ...)`
   resolves the `.exe` directly (the proxy doesn't pass `shell: true`, and
   post-CVE-2024-27980 Node refuses to launch `.cmd` files via `spawn` without
   it). Re-run this copy if Claude Code is updated.
6. `.env`: pre-filled to target the local proxy (see [.env](.env)).

## How to run an analysis

Two terminals.

**Terminal A — proxy:**

```powershell
claude-proxy
```

Default port 3456. Keep it open. `Ctrl+C` to stop.

**Terminal B — TradingAgents:**

```powershell
cd c:\Users\HP\Desktop\Agent\TradingAgents
.\.venv\Scripts\Activate.ps1

# Interactive CLI (ticker picker, analyst toggles, etc.)
tradingagents

# OR programmatic run
python main.py
```

## Verifying the wiring

```powershell
# Proxy live?
curl http://127.0.0.1:3456/health

# Models exposed?
curl http://127.0.0.1:3456/v1/models

# End-to-end LangChain → proxy → Claude CLI → Claude Max
.\.venv\Scripts\python.exe smoke_test.py
# expected last line: LLM response: TRADINGAGENTS_PROXY_OK
```

## Tuning cost / quota

`.env` defaults: Opus 4.7 for deep thinking, Haiku 4.5 for quick thinking.
Opus burns Max quota fast — for routine runs, swap deep to Sonnet:

```
TRADINGAGENTS_DEEP_THINK_LLM=claude-sonnet-4-6
```

Other knobs:

- `TRADINGAGENTS_MAX_DEBATE_ROUNDS` / `TRADINGAGENTS_MAX_RISK_ROUNDS` —
  bull/bear debate and risk discussion depth. Each extra round roughly
  doubles deep-think token spend for that stage.
- Data vendor: defaults to `yfinance` (free, no key). Switch to Alpha Vantage
  by setting `ALPHA_VANTAGE_API_KEY=...` and editing `data_vendors` in
  `tradingagents/default_config.py` (or override at runtime).

## Caveats — read before sustained use

- **ToS gray area.** Anthropic does not officially support using Max
  subscription as an API. `openclaw-claude-proxy` does not extract OAuth
  tokens — it spawns `claude` and lets the CLI authenticate normally — so
  it is closer to "headless Claude Code" than to token replay. Still, this
  is not the same as a paid API contract, and Anthropic could rate-limit or
  block sustained third-party usage. Use for personal research; do not
  resell or build a product on top of it.
- **Rate limits hit hard.** A full TradingAgents run (analysts + debate +
  risk + portfolio) can chain dozens of Opus calls. If you hit the Max
  weekly limit mid-run, the proxy returns errors and the agent graph may
  fail. Start with Haiku/Sonnet for testing.
- **Big prompt overhead.** Every proxied call carries Claude Code's full
  system prompt (~45k tokens). You'll see `cache_creation_input_tokens`
  in the proxy's usage stats. Cache hits keep cost manageable on later
  turns, but cold-start is expensive on the Max quota counter.
- **No streaming UI in TradingAgents.** The smoke test confirms
  non-streaming Chat Completions. The interactive CLI uses LangGraph and
  may invoke streaming under the hood; if you see streaming errors, force
  non-stream by adjusting the LangChain client kwargs in
  `tradingagents/llm_clients/openai_client.py`.

## File map

```
c:\Users\HP\Desktop\Agent\
├── TradingAgents\          # this repo (cloned)
│   ├── .env                # routes LLM calls to local proxy
│   ├── .venv\              # python deps
│   ├── smoke_test.py       # end-to-end LangChain → proxy probe
│   └── RUN_LOCAL.md        # this file
└── claude-proxy\           # source checkout (npm dist is what runs)
```
