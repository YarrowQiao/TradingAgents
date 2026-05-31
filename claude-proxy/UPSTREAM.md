# claude-proxy（已并入本项目）

本目录是 **claude-proxy** 的打包副本（vendored copy），已并入 TradingAgents，
让本项目自带这个「OpenAI 兼容的 Claude Code 代理」后端。
TradingAgents 通过 `http://127.0.0.1:3456/v1` 调用它。

## 来源（上游）

- **上游仓库：** https://github.com/mehdic/claude-proxy.git
- **打包自 commit：** `181c554f9442c761fbcff8665fcf9ec5be6e7b75`（分支 `main`）
- **本地跟踪检出：** 保留一份 origin 指向 mehdic 的 claude-proxy 克隆，作为拉取上游更新的地方。

## 运行方法

```bash
cd claude-proxy
npm install
npm run build
npm start          # 启动后监听 http://127.0.0.1:3456/v1
```

可选：覆盖预热的模型列表

```bash
CLAUDE_PROXY_PREWARM_MODELS="claude-opus-4-8,claude-sonnet-4-6,claude-haiku-4-5-20251001" npm start
```

## 从上游刷新

因为这是「直接复制」而非 git 子模块，上游有更新时按下面步骤刷新：

```bash
# 1. 在你那份 origin 指向 mehdic 的 claude-proxy 克隆里：
git pull origin main

# 2. 从该克隆重新打包进本目录（在克隆里执行，排除 traces.sqlite）：
git archive --prefix=claude-proxy/ HEAD | \
  tar -x --exclude='claude-proxy/traces.sqlite' -C /path/to/TradingAgents

# 3. 更新上面的「打包自 commit」SHA，然后在 TradingAgents 里提交。
```

## 相对上游的本地新增改动

本副本包含尚未推回 mehdic 上游的改动：

- `claude-opus-4-8` 模型注册（预热默认、模型路由、/v1/models、metrics、pricing）
- Windows 下直接定位 `claude.exe`：`src/subprocess/cli-resolver.ts`
- Windows 的 MCP 配置走临时文件 + `mcp__*__*` 自动放行：`stream-json-manager.ts`

如果将来把这些推回 mehdic，可以把本目录改成 `git subtree` 以实现双向同步。
