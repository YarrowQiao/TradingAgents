"""Lite PDF report generator.

Strips the full TradingAgents report down to sections 1 (analysts),
3 (trading), 5 (portfolio) — skipping the debate (2) and risk
committee (4) sections that account for most of the page count. Wired
into save_report_to_disk so every CLI/main.py run produces both
complete_report.* and <folder>+股票分析.* automatically.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

ROLE_LABELS = {
    # 1_analysts
    "market":       "Market Analyst",
    "sentiment":    "Sentiment Analyst",
    "news":         "News Analyst",
    "fundamentals": "Fundamentals Analyst",
    # 2_research
    "bull":         "Bull Researcher",
    "bear":         "Bear Researcher",
    "manager":      "Research Manager",
    # 3_trading
    "trader":       "Trader",
    # 4_risk
    "aggressive":   "Aggressive Analyst",
    "conservative": "Conservative Analyst",
    "neutral":      "Neutral Analyst",
    # 5_portfolio
    "decision":     "Portfolio Manager",
}

ALL_SECTIONS  = ("1_analysts", "2_research", "3_trading", "4_risk", "5_portfolio")
KEPT_SECTIONS = ("1_analysts", "3_trading", "5_portfolio")

_HEADING_RE = re.compile(r"^(#{1,6})(\s)")


def _demote_headings(text: str, levels: int = 2) -> str:
    """Bump every ATX heading in `text` down by `levels`, capping at H6.

    Skips lines inside fenced code blocks so comment characters in code
    samples ('# this is python') aren't mistaken for markdown headings.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        m = _HEADING_RE.match(line)
        if m:
            hashes = "#" * min(len(m.group(1)) + levels, 6)
            out.append(hashes + line[len(m.group(1)):])
        else:
            out.append(line)
    return "\n".join(out)


def _assemble_markdown(folder: Path, sections: tuple[str, ...]) -> Optional[str]:
    """Return the assembled markdown string, or None if nothing to assemble.

    Used by both the lite (sections=KEPT_SECTIONS) and full
    (sections=ALL_SECTIONS) generators so the heading layout stays
    identical between the two outputs.
    """
    parts: list[str] = [f"# {folder.name} 股票分析", ""]
    found_any = False
    for section in sections:
        sec_dir = folder / section
        if not sec_dir.is_dir():
            continue
        for md_file in sorted(sec_dir.glob("*.md")):
            label = ROLE_LABELS.get(md_file.stem, md_file.stem.replace("_", " ").title())
            content = md_file.read_text(encoding="utf-8")
            demoted = _demote_headings(content, levels=2)
            parts.extend([f"## {label}", "", demoted.strip(), ""])
            found_any = True
    return "\n".join(parts) if found_any else None


def _write_and_convert(folder: Path, md_name: str, md_text: str) -> Optional[Path]:
    """Write md_text to `folder/md_name` and produce the matching PDF.

    Deferred import on _convert_md_to_pdf because cli.main imports this
    module — a top-level import would deadlock at startup.
    """
    out_md = folder / md_name
    out_md.write_text(md_text, encoding="utf-8")
    from cli.main import _convert_md_to_pdf
    return _convert_md_to_pdf(out_md)


def generate_lite_for_folder(folder: Path) -> Optional[Path]:
    """Sections 1+3+5 only — `<folder>+股票分析.md/.pdf`."""
    md_text = _assemble_markdown(folder, KEPT_SECTIONS)
    if md_text is None:
        return None
    return _write_and_convert(folder, f"{folder.name}+股票分析.md", md_text)


def generate_full_for_folder(folder: Path) -> Optional[Path]:
    """All 5 sections — `complete_report.md/.pdf`."""
    md_text = _assemble_markdown(folder, ALL_SECTIONS)
    if md_text is None:
        return None
    return _write_and_convert(folder, "complete_report.md", md_text)
