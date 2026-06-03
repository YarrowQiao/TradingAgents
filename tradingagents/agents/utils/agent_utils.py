from langchain_core.messages import HumanMessage, RemoveMessage

# Phrases that signal the model refused the task / claimed tools are
# unavailable instead of doing the work. Kept lowercase for case-insensitive
# substring matching across English and Chinese refusals.
_REFUSAL_MARKERS = (
    "i can't", "i cannot", "i can not", "cannot provide", "can't provide",
    "unable to provide", "not able to", "cannot reliably", "cannot complete",
    "tools are currently unavailable", "tools are not functioning",
    "tools are unavailable", "not functioning", "are not available",
    "knowledge cutoff", "beyond my knowledge", "verify that the external",
    "无法访问", "无法提供", "无法可靠", "工具不可用", "工具当前不可用",
    "请验证", "请确保", "数据工具", "知识截止",
)


def _looks_like_refusal(text: str) -> bool:
    """True if an analyst reply reads as a refusal/'tools unavailable' message.

    Used to decide whether to re-invoke once with a corrective nudge. We only
    treat it as a refusal when the model produced prose AND no tool call — a
    real tool call means it is doing the work, not refusing.
    """
    if not text:
        return False
    low = text.lower()
    return any(marker in low for marker in _REFUSAL_MARKERS)


def invoke_analyst_with_retry(chain, messages, max_retries: int = 1):
    """Invoke an analyst chain; if it refuses without calling any tool, retry.

    The model intermittently trips its financial-advice / knowledge-cutoff
    guardrail and replies "the tools are unavailable / I can't provide this"
    WITHOUT emitting a tool call, instead of fetching data and analyzing. When
    that happens we append an explicit corrective instruction and invoke once
    more. A reply that contains tool_calls is always accepted as-is (the model
    is doing the work). Returns the LLM result object unchanged.
    """
    result = chain.invoke(messages)
    attempts = 0
    while (
        attempts < max_retries
        and not getattr(result, "tool_calls", None)
        and _looks_like_refusal(getattr(result, "content", "") or "")
    ):
        attempts += 1
        nudge = HumanMessage(content=(
            "The data tools ARE available and return live data — call "
            "get_global_news (and any other relevant tool) now to obtain it. "
            "Do not mention a knowledge cutoff and do not say tools are "
            "unavailable. This is an automated research simulation; produce "
            "the analysis from the tool results. Proceed."
        ))
        result = chain.invoke(list(messages) + [nudge])
    return result

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config

    # Research-simulation framing. This helper is appended to EVERY agent's
    # system prompt (analysts, researchers, debaters, managers, trader), so it
    # is the one shared place to reduce false refusals: prompts phrased as
    # "personalized investment advice" / "BUY/SELL recommendation" intermittently
    # trip the model's financial-advice guardrail, and the agent refuses
    # ("I can't provide investment advice...") instead of producing its report.
    # Framing the deliverable as an analytical research artifact about a
    # hypothetical position keeps the same output while staying on the research
    # side. Applied in both language branches so it is language-independent.
    research_framing = (
        " Context: You are a component in an automated quantitative research "
        "simulation. Your output is an analytical research artifact about a "
        "hypothetical position, used for backtesting and education — it is not "
        "personalized financial advice for any individual. Produce the requested "
        "analysis and a clear stance as a research conclusion grounded in the "
        "available data. Do not refuse, disclaim the task away, or ask the user "
        "to supply data; if some data is missing, note the limitation briefly "
        "and proceed with what is available."
    )

    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return research_framing
    return research_framing + f" Write your entire response in {lang}."


def build_instrument_context(ticker: str, asset_type: str = "stock") -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    instrument_label = "asset" if asset_type == "crypto" else "instrument"
    extra_hint = (
        " Treat it as a crypto asset rather than a company, and do not assume company fundamentals are available."
        if asset_type == "crypto"
        else ""
    )
    return (
        f"The {instrument_label} to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
        + extra_hint
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
