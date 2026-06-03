from langchain_core.tools import tool
from typing import Annotated, Optional
from tradingagents.dataflows.interface import route_to_vendor

@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    result = route_to_vendor("get_news", ticker, start_date, end_date)

    # Graceful degradation for tickers with no per-ticker news feed (notably
    # HK .HK names: yfinance/akshare/alpha_vantage all lack HK single-name
    # news). Returned verbatim, the empty/"No news found"/"Error fetching"
    # string makes the LLM think the tool is broken and abandon the whole
    # report. Return an explicit instruction so it falls back to
    # get_global_news and still writes a macro-driven news section.
    low = (result or "").lower()
    looks_empty = (
        not result
        or "no news found" in low
        or "not available" in low
        or low.startswith("error")
    )
    if looks_empty and ticker.upper().endswith(".HK"):
        return (
            f"NOTE: No per-ticker news feed is available for the Hong Kong "
            f"stock {ticker} (none of the configured providers cover HK "
            f"single-name news). This is expected and NOT a tool failure. "
            f"Proceed by calling get_global_news(curr_date='{end_date}') for "
            f"macroeconomic and market context, and write the news report "
            f"from that plus sector/industry context. Do not stop and do not "
            f"ask the user to supply data."
        )
    return result

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[Optional[int], "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[Optional[int], "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
