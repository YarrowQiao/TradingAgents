"""AKShare vendor: A-share data source for TradingAgents.

Mirrors the 8 method surface of the yfinance vendor so route_to_vendor
can dispatch to either based on ticker suffix (.SZ/.SS/.BJ → akshare,
no suffix → yfinance unchanged). Each method returns the same string
shape its yfinance counterpart returns so downstream prompts and
parsers don't need to special-case the source.

Network note: AKShare hits mainland Chinese endpoints (eastmoney,
sina, baidu). On machines with HTTP_PROXY pointing at a foreign-only
VPN those requests fail with ProxyError. We append the relevant
domains to NO_PROXY at import time so AKShare bypasses the proxy
without touching the global proxy config — yfinance / other US
endpoints keep using the proxy as before.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, Optional

# Domains AKShare contacts. Adding to NO_PROXY rather than clearing
# HTTP_PROXY/HTTPS_PROXY so other vendors (yfinance, alpha_vantage,
# news APIs) continue to honor the user's existing proxy config.
_AKSHARE_DOMAINS = (
    "eastmoney.com,"
    "push2.eastmoney.com,push2his.eastmoney.com,datacenter-web.eastmoney.com,"
    "datacenter.eastmoney.com,emweb.securities.eastmoney.com,"
    "sina.com.cn,finance.sina.com.cn,hq.sinajs.cn,"
    "baidu.com,gushitong.baidu.com,"
    "szse.cn,sse.com.cn,"
    "tushare.pro,akshare.akfamily.xyz"
)
_existing_no_proxy = os.environ.get("NO_PROXY", "")
os.environ["NO_PROXY"] = ",".join(p for p in (_existing_no_proxy, _AKSHARE_DOMAINS) if p)
# Lowercase variant — some HTTP libs only check the lowercase form.
os.environ["no_proxy"] = os.environ["NO_PROXY"]

import akshare as ak  # noqa: E402  must come after NO_PROXY tweak

import pandas as pd  # noqa: E402
from stockstats import wrap as stockstats_wrap  # noqa: E402

logger = logging.getLogger(__name__)


# Suffix detection — exported so route_to_vendor can use the same rule.
A_SHARE_SUFFIXES = (".SZ", ".SS", ".BJ")
HK_SHARE_SUFFIXES = (".HK",)


def _retry(fn: Callable, *args, retries: int = 3, base_delay: float = 1.5, **kwargs):
    """Call AKShare fn with exponential backoff on transient network errors.

    EastMoney occasionally drops connections under burst load. Without
    retries one bad turn will silently kill an analyst report. We don't
    treat HTTP-status errors as transient — only socket-level disconnects.
    """
    import requests
    transient = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except transient as e:
            if attempt == retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning("AKShare %s transient %s, retrying in %.1fs", fn.__name__, type(e).__name__, delay)
            time.sleep(delay)


def is_a_share(ticker: str) -> bool:
    return ticker.upper().endswith(A_SHARE_SUFFIXES)


def _strip_suffix(ticker: str) -> str:
    """Return the bare 6-digit code AKShare's price/news APIs expect."""
    up = ticker.upper()
    for sfx in A_SHARE_SUFFIXES:
        if up.endswith(sfx):
            return up[: -len(sfx)]
    return up


def is_hk_share(ticker: str) -> bool:
    return ticker.upper().endswith(HK_SHARE_SUFFIXES)


def _hk_code(ticker: str) -> str:
    """`09992.HK` / `9992.HK` → `09992` — the 5-digit code AKShare's HK APIs want."""
    up = ticker.upper()
    if up.endswith(".HK"):
        up = up[:-3]
    return up.zfill(5)


def _em_prefixed_symbol(ticker: str) -> str:
    """`002714.SZ` → `SZ002714`, `600519.SS` → `SH600519` for EM financial APIs."""
    up = ticker.upper()
    if up.endswith(".SZ"):
        return "SZ" + up[:-3]
    if up.endswith(".SS"):
        return "SH" + up[:-3]
    if up.endswith(".BJ"):
        return "BJ" + up[:-3]
    return up  # already prefixed or unsuffixed bare code


def _yyyymmdd(date_str: str) -> str:
    """`2026-05-22` → `20260522` — the format AKShare's hist API wants."""
    return date_str.replace("-", "")


def _tx_symbol(ticker: str) -> str:
    """`002714.SZ`/`000001` → `sz002714`, `600519.SS` → `sh600519` for the
    Tencent (stock_zh_a_hist_tx) API, which wants a lowercase exchange prefix."""
    up = ticker.upper()
    if up.endswith(".SZ"):
        return "sz" + up[:-3]
    if up.endswith(".SS"):
        return "sh" + up[:-3]
    if up.endswith(".BJ"):
        return "bj" + up[:-3]
    code = up
    # Bare 6-digit code: infer exchange from the leading digit.
    # 6xxxxx → Shanghai; 0/3xxxxx → Shenzhen; 8/4xxxxx → Beijing.
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("8", "4")):
        return "bj" + code
    return "sz" + code


def _fetch_a_share_ohlcv(symbol: str, start_yyyymmdd: str, end_yyyymmdd: str) -> pd.DataFrame:
    """Fetch A-share daily OHLCV, returning a DataFrame with English columns
    Date/Open/High/Low/Close/Volume.

    Source order: Tencent (stock_zh_a_hist_tx) FIRST, EastMoney
    (stock_zh_a_hist) as fallback. EastMoney rate-limits aggressively by IP
    (a single analyst run fires ~7 indicator calls in the same second, which
    trips the limiter and the whole run dies with ConnectionError). Tencent is
    an independent backend not subject to that limiter. Tencent omits a true
    volume column (only `amount`), so we map amount→Volume there; the headline
    indicators (SMA/EMA/RSI/MACD/Bollinger/ATR) don't use volume, and the
    EastMoney fallback still carries the real volume when it is reachable.
    """
    # Primary: Tencent
    try:
        df = _retry(
            ak.stock_zh_a_hist_tx,
            symbol=_tx_symbol(symbol),
            start_date=start_yyyymmdd,
            end_date=end_yyyymmdd,
            adjust="qfq",
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "date": "Date", "open": "Open", "close": "Close",
                "high": "High", "low": "Low", "amount": "Volume",
            })
            for col in ("Open", "High", "Low", "Close", "Volume"):
                if col not in df.columns:
                    df[col] = pd.NA
            return df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        logger.warning("Tencent A-share fetch failed for %s (%s); falling back to EastMoney",
                       symbol, type(e).__name__)

    # Fallback: EastMoney (has real volume when reachable)
    df = _retry(
        ak.stock_zh_a_hist,
        symbol=_strip_suffix(symbol),
        period="daily",
        start_date=start_yyyymmdd,
        end_date=end_yyyymmdd,
        adjust="qfq",
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df = df.rename(columns={
        "日期": "Date", "开盘": "Open", "收盘": "Close",
        "最高": "High", "最低": "Low", "成交量": "Volume", "成交额": "Amount",
    })
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


_HK_COL_MAP = {
    "日期": "Date", "开盘": "Open", "收盘": "Close",
    "最高": "High", "最低": "Low", "成交量": "Volume", "成交额": "Amount",
}


def _get_stock_data_hk(symbol: str, start_date: str, end_date: str) -> str:
    """OHLCV for a HK-listed stock (e.g. 09992.HK), formatted like get_stock_data."""
    code = _hk_code(symbol)
    df = _retry(
        ak.stock_hk_hist,
        symbol=code,
        period="daily",
        start_date=_yyyymmdd(start_date),
        end_date=_yyyymmdd(end_date),
        adjust="",  # HK adjusted series are spotty on eastmoney; use raw
    )
    if df is None or df.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"
    df = df.rename(columns=_HK_COL_MAP)
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].set_index("Date")
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col].round(3)
    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Total records: {len(df)}\n"
        f"# Source: AKShare HK (eastmoney) / Adjusted: none\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv()


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """OHLCV for an A-share or HK stock over a date range, like yfinance's CSV."""
    if is_hk_share(symbol):
        return _get_stock_data_hk(symbol, start_date, end_date)
    df = _fetch_a_share_ohlcv(symbol, _yyyymmdd(start_date), _yyyymmdd(end_date))
    if df.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    df = df.set_index("Date")
    for col in ("Open", "High", "Low", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round(2)

    csv_string = df.to_csv()
    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Total records: {len(df)}\n"
        f"# Source: AKShare (tencent primary, eastmoney fallback) / Adjusted: forward (qfq)\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + csv_string


def _load_ohlcv_for_indicators(symbol: str, curr_date: str) -> pd.DataFrame:
    """Load ~1y of OHLCV ending at curr_date, formatted for stockstats.

    1y (~250 trading days) is enough to warm up a 200-SMA and still
    have plenty of points before the lookback window. Larger windows
    were getting rejected by eastmoney as bot-like burst traffic.
    """
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - pd.DateOffset(years=1)
    if is_hk_share(symbol):
        df = _retry(
            ak.stock_hk_hist,
            symbol=_hk_code(symbol),
            period="daily",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
            adjust="",
        )
        df = df.rename(columns={
            "日期": "Date", "开盘": "Open", "收盘": "Close",
            "最高": "High", "最低": "Low", "成交量": "Volume",
        })
    else:
        # Tencent-primary / EastMoney-fallback; already English columns.
        df = _fetch_a_share_ohlcv(
            symbol, start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")
        )
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Date"] <= end_dt]
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    return df


def get_indicators(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    """Compute one technical indicator on AKShare OHLCV via stockstats.

    Mirrors yfinance's get_stock_stats_indicators_window output shape so
    the analyst prompt sees the same per-day indicator table regardless
    of vendor.
    """
    df = _load_ohlcv_for_indicators(symbol, curr_date)
    if df.empty:
        return f"No data found for symbol '{symbol}' to compute {indicator}"

    indicator = indicator.strip().lower()
    stats = stockstats_wrap(df.copy())
    try:
        stats[indicator]  # triggers the computation column
    except Exception as e:
        return f"Indicator '{indicator}' not supported by stockstats: {e}"

    # Build per-day report over the lookback window, matching the
    # yfinance variant's ## header + date: value lines layout.
    series = stats[indicator]
    series.index = pd.to_datetime(df["Date"].values)
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - pd.Timedelta(days=look_back_days)
    window = series[(series.index >= start_dt) & (series.index <= end_dt)]

    lines = [f"## {indicator} values from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:"]
    if window.empty:
        lines.append("(no trading days in this window)")
    else:
        for dt, val in window.items():
            if pd.isna(val):
                lines.append(f"{dt.strftime('%Y-%m-%d')}: N/A")
            else:
                lines.append(f"{dt.strftime('%Y-%m-%d')}: {val:.4f}")
    return "\n".join(lines)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Per-ticker news from EastMoney, filtered to the date range."""
    if is_hk_share(ticker):
        return (
            f"Per-ticker news for HK stocks ({ticker}) is not available from the "
            f"current AKShare/EastMoney per-ticker feed (it covers mainland "
            f"A-shares only). Use macro/sector news for HK names."
        )
    code = _strip_suffix(ticker)
    df = _retry(ak.stock_news_em, symbol=code)
    if df.empty:
        return f"No news found for {ticker}"

    df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)  # inclusive end
    df = df[(df["发布时间"] >= start_dt) & (df["发布时间"] < end_dt)]

    # EastMoney's stock_news_em matches the ticker against arbitrary page
    # mentions (e.g., the code appearing in a market-rankings list), so
    # the dataframe often contains stories about OTHER companies that
    # merely co-occur in those lists. Require the code itself to appear
    # in the title or body, which reliably filters those out for ticker
    # codes specific enough to not collide with normal prose.
    if not df.empty:
        code_str = str(code)
        title_match = df["新闻标题"].astype(str).str.contains(code_str, na=False)
        body_match = df["新闻内容"].astype(str).str.contains(code_str, na=False)
        df = df[title_match | body_match]

    if df.empty:
        return (
            f"No ticker-specific news for {ticker} in the window "
            f"{start_date} → {end_date}. EastMoney's per-ticker feed "
            f"covers ~30 days and is sparse for lower-volume names."
        )

    lines = [f"# News for {ticker} ({start_date} → {end_date})", ""]
    for _, row in df.iterrows():
        ts = row["发布时间"].strftime("%Y-%m-%d %H:%M") if pd.notna(row["发布时间"]) else ""
        title = str(row.get("新闻标题", "")).strip()
        source = str(row.get("文章来源", "")).strip()
        url = str(row.get("新闻链接", "")).strip()
        body = str(row.get("新闻内容", "")).strip().replace("\n", " ")
        if len(body) > 400:
            body = body[:400] + "..."
        lines.append(f"## {title}")
        lines.append(f"*{ts} — {source}*  [link]({url})")
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def get_global_news(curr_date: str, look_back_days: Optional[int] = None, limit: Optional[int] = None) -> str:
    """Macro/economic events from Baidu calendar. Not ticker-specific.

    AKShare's news_economic_baidu returns the next ~7 days of releases
    plus recent past events. We filter to the look_back_days window
    ending at curr_date and rank by importance flag.
    """
    look_back_days = look_back_days or 7
    limit = limit or 15

    try:
        df = _retry(ak.news_economic_baidu)
    except Exception as e:
        return f"Macro calendar fetch failed: {e}"

    if df.empty:
        return "No macro events available."

    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    end_dt = pd.to_datetime(curr_date)
    start_dt = end_dt - pd.Timedelta(days=look_back_days)
    df = df[(df["日期"] >= start_dt) & (df["日期"] <= end_dt)]
    if df.empty:
        return f"No macro events in the {look_back_days}-day window ending {curr_date}."

    # Sort by importance descending so the top entries are the
    # market-moving ones; fall back to time-sorted within importance.
    df = df.sort_values(["重要性", "日期", "时间"], ascending=[False, False, False])
    df = df.head(limit)

    lines = [f"# Macroeconomic events ({start_dt.strftime('%Y-%m-%d')} → {curr_date})", ""]
    for _, row in df.iterrows():
        date = row["日期"].strftime("%Y-%m-%d") if pd.notna(row["日期"]) else ""
        time = str(row.get("时间", "")).strip()
        region = str(row.get("地区", "")).strip()
        event = str(row.get("事件", "")).strip()
        actual = row.get("公布", "")
        expected = row.get("预期", "")
        prev = row.get("前值", "")
        importance = row.get("重要性", "")
        stars = "★" * int(importance) if isinstance(importance, (int, float)) and not pd.isna(importance) else ""
        lines.append(f"- **{date} {time}** [{region}] {stars} {event}")
        lines.append(f"  - 公布={actual} 预期={expected} 前值={prev}")
    return "\n".join(lines)


def _get_fundamentals_hk(ticker: str, curr_date: str) -> str:
    """HK fundamentals via EastMoney HK financial-analysis indicators.

    Column names vary across akshare versions, so render generically rather
    than assuming a fixed schema — an upstream rename can't silently break it.
    """
    code = _hk_code(ticker)
    try:
        df = _retry(ak.stock_financial_hk_analysis_indicator_em, symbol=code, indicator="年度")
    except Exception as e:
        return f"Fundamentals fetch failed for {ticker} (HK): {e}"
    if df is None or df.empty:
        return f"No fundamentals available for {ticker} (HK)"
    return (
        f"# Fundamentals for {ticker} (HK) as of {curr_date}\n"
        f"# Source: 东方财富 港股财务分析指标 (年度) via AKShare\n\n"
        + df.head(8).to_string(index=False)
    )


def get_fundamentals(ticker: str, curr_date: str) -> str:
    """Summary fundamentals — Tonghuashun (A-share) or EastMoney HK indicators.

    Returns the latest reporting period plus YoY context.
    """
    if is_hk_share(ticker):
        return _get_fundamentals_hk(ticker, curr_date)
    code = _strip_suffix(ticker)
    try:
        df = _retry(ak.stock_financial_abstract_ths, symbol=code)
    except Exception as e:
        return f"Fundamentals fetch failed for {ticker}: {e}"
    if df.empty:
        return f"No fundamentals available for {ticker}"

    df["报告期"] = pd.to_datetime(df["报告期"], errors="coerce")
    end_dt = pd.to_datetime(curr_date)
    df = df[df["报告期"] <= end_dt].sort_values("报告期", ascending=False)
    if df.empty:
        return f"No fundamentals reported before {curr_date} for {ticker}"

    latest = df.iloc[0]
    lines = [
        f"# Fundamentals for {ticker} as of {curr_date}",
        f"Source: 同花顺财务摘要 via AKShare",
        f"Latest reporting period: {latest['报告期'].strftime('%Y-%m-%d')}",
        "",
        "## Latest period key metrics",
    ]
    for col in df.columns:
        if col == "报告期":
            continue
        val = latest[col]
        if pd.isna(val) or val == "" or val is False:
            continue
        lines.append(f"- **{col}**: {val}")

    # Trend: show last 4 periods of profit / revenue for context
    trend_cols = [c for c in ("报告期", "营业总收入", "净利润", "净资产收益率", "销售毛利率", "销售净利率") if c in df.columns]
    trend = df.head(4)[trend_cols]
    lines.extend(["", "## Last 4 reporting periods (YoY context)", trend.to_string(index=False)])
    return "\n".join(lines)


def _financial_statement_csv(ak_fn, ticker: str, freq: str, curr_date: Optional[str], label: str) -> str:
    """Shared shape for balance/cashflow/income — wraps an EM report API.

    freq='annual' keeps only year-end reports; 'quarterly' (default) keeps all.
    """
    em_symbol = _em_prefixed_symbol(ticker)
    try:
        df = _retry(ak_fn, symbol=em_symbol)
    except Exception as e:
        return f"{label} fetch failed for {ticker}: {e}"
    if df.empty:
        return f"No {label} data for {ticker}"

    if "REPORT_DATE" in df.columns:
        df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
        if curr_date:
            end_dt = pd.to_datetime(curr_date)
            df = df[df["REPORT_DATE"] <= end_dt]
        if freq == "annual":
            df = df[df["REPORT_DATE"].dt.month == 12]
        df = df.sort_values("REPORT_DATE", ascending=False)

    # Drop bookkeeping columns the LLM doesn't care about; keep the
    # actual line items. The first ~12 cols are metadata (ORG_CODE etc.)
    drop_cols = {
        "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "ORG_TYPE",
        "REPORT_TYPE", "SECURITY_TYPE_CODE", "NOTICE_DATE", "UPDATE_DATE", "CURRENCY",
    }
    keep = [c for c in df.columns if c not in drop_cols]
    df = df[keep].head(8)  # 8 most recent reporting periods

    header = (
        f"# {label} for {ticker} ({freq})\n"
        f"# Periods returned: {len(df)} (most recent first)\n"
        f"# Source: AKShare (eastmoney) — cutoff {curr_date or 'none'}\n\n"
    )
    return header + df.to_csv(index=False)


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return _financial_statement_csv(
        ak.stock_balance_sheet_by_report_em, ticker, freq, curr_date, "Balance Sheet"
    )


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return _financial_statement_csv(
        ak.stock_cash_flow_sheet_by_report_em, ticker, freq, curr_date, "Cash Flow Statement"
    )


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return _financial_statement_csv(
        ak.stock_profit_sheet_by_report_em, ticker, freq, curr_date, "Income Statement"
    )
