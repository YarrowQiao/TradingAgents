"""Batch-regenerate consolidated reports across every reports/ subfolder.

Per-run generation is automatic — save_report_to_disk calls
generate_full_for_folder and generate_lite_for_folder at the end of
every analysis. This script exists for backfilling old reports or for
re-running after ROLE_LABELS / KEPT_SECTIONS in cli/lite_report.py have
changed.

Both the full (complete_report.md/.pdf) and lite (<folder>+股票分析.md/.pdf)
consolidations are rewritten in place — sub-folder .md files
(1_analysts/, 2_research/, ...) are read but never modified.

    .venv\\Scripts\\python.exe scripts\\generate_lite_reports.py
"""

from __future__ import annotations

from pathlib import Path

from cli.lite_report import generate_full_for_folder, generate_lite_for_folder


def main() -> None:
    reports_root = Path(__file__).resolve().parents[1] / "reports"
    if not reports_root.is_dir():
        print(f"reports dir not found: {reports_root}")
        return

    for folder in sorted(reports_root.iterdir()):
        if not folder.is_dir():
            continue
        full = generate_full_for_folder(folder)
        lite = generate_lite_for_folder(folder)
        full_status = full.name if full else "(no content)"
        lite_status = lite.name if lite else "(no content)"
        print(f"[{folder.name}]")
        print(f"  full -> {full_status}")
        print(f"  lite -> {lite_status}")


if __name__ == "__main__":
    main()
