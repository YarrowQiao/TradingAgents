"""Smoke test: exercise TradingAgents LLM stack end-to-end through claude-proxy.

Imports tradingagents (which auto-loads .env), then instantiates a quick LLM
client via the same factory the real run uses. Skips data fetching and the
full agent graph — just confirms the proxy + LangChain plumbing is wired up.
"""
import tradingagents  # triggers .env load + side-effect imports
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.default_config import DEFAULT_CONFIG

print("provider     :", DEFAULT_CONFIG["llm_provider"])
print("backend_url  :", DEFAULT_CONFIG["backend_url"])
print("deep_model   :", DEFAULT_CONFIG["deep_think_llm"])
print("quick_model  :", DEFAULT_CONFIG["quick_think_llm"])
print()

client = create_llm_client(
    provider=DEFAULT_CONFIG["llm_provider"],
    model=DEFAULT_CONFIG["quick_think_llm"],
    base_url=DEFAULT_CONFIG["backend_url"],
)
llm = client.get_llm()
result = llm.invoke("Reply with exactly: TRADINGAGENTS_PROXY_OK")
print("LLM response:", result.content if hasattr(result, "content") else result)
