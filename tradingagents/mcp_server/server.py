"""MCP server exposing TradingAgents data tools natively to Claude Code.

The 4 analyst agents originally bind these as LangChain tools and send them
through claude-proxy's OpenAI-compatible bridge. The bridge injects tool
schemas as prompt text and asks Claude to emit JSON tool_call blocks —
which Claude Code routinely refuses to do, hence the "I cannot access
get_indicators" failures we observed.

By exposing the same functions through MCP, claude-proxy can mount this
server via `--mcp-config` so Claude Code sees them as NATIVE callable
tools (mcp__tradingagents__get_stock_data, etc.) and invokes them via
the real Anthropic tool_use protocol — no JSON-in-prose bridge, no
refusals.

Each tool is a thin wrapper around `route_to_vendor`, the same dispatch
function the LangChain `@tool` wrappers use. We bypass `@tool` here so
LangChain isn't required at MCP-server side and so the docstrings stay
verbose enough for Claude to understand the parameter semantics without
inheriting the LangChain `Annotated` machinery.

Run standalone:
    python -m tradingagents.mcp_server
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Load .env from the TradingAgents project root so the server picks up the
# same TRADINGAGENTS_*, ALPHA_VANTAGE_API_KEY, etc. that the CLI uses,
# regardless of which cwd claude-proxy spawns us from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP
from tradingagents.dataflows.interface import route_to_vendor

mcp = FastMCP("tradingagents")

# Suppress any tool-side print() chatter so it doesn't corrupt MCP's
# stdio JSON-RPC stream. yfinance and a few helpers occasionally print
# progress/warnings to stdout; route those to stderr instead.
_log = logging.getLogger("tradingagents.mcp_server")


def _call(method: str, *args, **kwargs) -> str:
    """Route a tool call through TradingAgents' vendor dispatch.

    Stdout from inside the tool is buffered and redirected to stderr so
    only the actual return string reaches the MCP transport.
    """
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = route_to_vendor(method, *args, **kwargs)
    except Exception as e:
        # FastMCP will surface the exception to the model as a tool
        # error. Log to stderr so we can debug from the proxy console.
        _log.exception("route_to_vendor(%s) failed", method)
        raise
    if buf.getvalue():
        sys.stderr.write(buf.getvalue())
    return result


@mcp.tool()
def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Retrieve OHLCV stock price data for a ticker over a date range.

    Args:
        symbol: Ticker symbol (e.g. NVDA, 0700.HK, 002714.SZ).
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        Formatted text containing the price history. Use this before
        computing indicators or writing technical analysis.
    """
    return _call("get_stock_data", symbol, start_date, end_date)


@mcp.tool()
def get_indicators(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    """Retrieve a single technical indicator series for a ticker.

    Args:
        symbol: Ticker symbol.
        indicator: One of: close_50_sma, close_200_sma, close_10_ema,
            macd, macds, macdh, rsi, boll, boll_ub, boll_lb, atr,
            vwma, mfi. Call once per indicator (no comma-lists).
        curr_date: Trading date you are analyzing, YYYY-MM-DD.
        look_back_days: How many trading days of history to include (default 30).

    Returns:
        Formatted text showing the indicator values over the lookback window.
    """
    return _call("get_indicators", symbol, indicator, curr_date, look_back_days)


@mcp.tool()
def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Retrieve ticker-specific news articles for a date range.

    Args:
        ticker: Ticker symbol.
        start_date: YYYY-MM-DD.
        end_date: YYYY-MM-DD.

    Returns:
        Formatted markdown with article titles, summaries, publishers, and links.
    """
    return _call("get_news", ticker, start_date, end_date)


@mcp.tool()
def get_global_news(curr_date: str, look_back_days: Optional[int] = None, limit: Optional[int] = None) -> str:
    """Retrieve macroeconomic / global market news (not ticker-specific).

    Args:
        curr_date: Reference date, YYYY-MM-DD.
        look_back_days: Days of history; omit to use the configured default (7).
        limit: Max articles; omit to use the configured default (10).

    Returns:
        Formatted markdown with articles relevant to broad market topics
        (Fed, earnings season, geopolitics, commodities).
    """
    return _call("get_global_news", curr_date, look_back_days, limit)


@mcp.tool()
def get_fundamentals(ticker: str, curr_date: str) -> str:
    """Retrieve comprehensive fundamental data for a company.

    Includes market cap, PE ratio, dividend yield, profitability metrics,
    growth metrics. Use before writing fundamental analysis.

    Args:
        ticker: Ticker symbol.
        curr_date: Reference date, YYYY-MM-DD.

    Returns:
        Formatted text report of the company's fundamentals.
    """
    return _call("get_fundamentals", ticker, curr_date)


@mcp.tool()
def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    """Retrieve balance sheet data for a company.

    Args:
        ticker: Ticker symbol.
        freq: 'annual' or 'quarterly' (default quarterly).
        curr_date: Reference date YYYY-MM-DD. Statements with dates after
            this are excluded so the analysis stays time-consistent.

    Returns:
        CSV-formatted balance sheet.
    """
    return _call("get_balance_sheet", ticker, freq, curr_date)


@mcp.tool()
def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    """Retrieve cash flow statement data for a company.

    Args:
        ticker: Ticker symbol.
        freq: 'annual' or 'quarterly' (default quarterly).
        curr_date: Reference date YYYY-MM-DD; later statements excluded.

    Returns:
        CSV-formatted cash flow statement.
    """
    return _call("get_cashflow", ticker, freq, curr_date)


@mcp.tool()
def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    """Retrieve income statement data for a company.

    Args:
        ticker: Ticker symbol.
        freq: 'annual' or 'quarterly' (default quarterly).
        curr_date: Reference date YYYY-MM-DD; later statements excluded.

    Returns:
        CSV-formatted income statement.
    """
    return _call("get_income_statement", ticker, freq, curr_date)


def main() -> None:
    """Entry point: start the MCP server speaking stdio."""
    # All stderr goes to the proxy's console — handy for debugging which
    # tool got called with which args during a live run.
    logging.basicConfig(
        level=os.environ.get("TRADINGAGENTS_MCP_LOG_LEVEL", "INFO"),
        stream=sys.stderr,
        format="[tradingagents-mcp] %(levelname)s %(message)s",
    )
    _log.info("starting MCP server, project root=%s", _PROJECT_ROOT)
    mcp.run()


if __name__ == "__main__":
    main()
