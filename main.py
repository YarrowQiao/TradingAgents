import datetime
from pathlib import Path

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from cli.main import save_report_to_disk

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
config = DEFAULT_CONFIG.copy()

ta = TradingAgentsGraph(debug=True, config=config)

ticker = "GOOG"
trade_date = "2026-05-22"

# propagate returns (final_state, decision). final_state holds every
# sub-report (market/sentiment/news/fundamentals + debate + risk + PM);
# decision is just the BUY/SELL/HOLD signal. Keep both so the full
# report can be persisted via the same path the CLI uses.
final_state, decision = ta.propagate(ticker, trade_date)

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
save_path = Path(__file__).parent / "reports" / f"{ticker}_{timestamp}"
md_path = save_report_to_disk(final_state, ticker, save_path)

print("\n=== Decision ===")
print(decision)
print(f"\n=== Full report (md) ===\n{md_path}")
pdf_path = md_path.with_suffix(".pdf")
if pdf_path.exists():
    print(f"=== Full report (pdf) ===\n{pdf_path}")

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
