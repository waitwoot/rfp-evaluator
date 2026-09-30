#!/usr/bin/env python3
"""Headless evaluation run with JSON export.

    python scripts/run_cli.py --provider mock
    python scripts/run_cli.py --provider openai \\
        --base-url https://api.groq.com/openai/v1 --model openai/gpt-oss-120b \\
        --out sample_output/sample_rfp_run.json
    python scripts/run_cli.py --provider mock --fault malformed_values
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfp import config, db, orchestrator  # noqa: E402
from rfp.agents.evaluation_agent import FAULT_MODES  # noqa: E402
from rfp.samples import sample_suppliers  # noqa: E402


def print_leaderboard(result: dict) -> None:
    rows = result["suppliers"]
    print(f"\nRFP_RUN_ID : {result['rfp_run_id']}")
    print(f"provider   : {result['llm_provider']}:{result['llm_model']}"
          + (f" via {result['llm_base_url']}" if result.get("llm_base_url") else ""))
    print(f"status     : {result['status']}"
          + (f"   fault: {result['fault_mode']}" if result.get("fault_mode") else ""))

    print(f"\n{'Rank':<5}{'Supplier':<18}{'Absolute':>9}{'PPI':>10}"
          f"{'Submitted':>13}{'Exp':>5}")
    print("-" * 60)
    for row in rows:
        print(f"{row['final_rank']:<5}{row['supplier_name']:<18}"
              f"{row['absolute_score']:>9.2f}{row['ppi']:>10.4f}"
              f"{row['submission_date'] or '-':>13}{row['experience_rating']:>5g}")
    print("-" * 60)

    if result.get("tie_breaks"):
        print("\nTie-break decisions (adjacent pairs):")
        for decision in result["tie_breaks"]:
            print(f"  [rule {decision['rule_level']}] {decision['explanation']}")

    if result.get("skipped"):
        print("\nSkipped documents:")
        for item in result["skipped"]:
            print(f"  {item['supplier_name']}: [{item['code']}] {item['reason']}")

    warnings = result.get("warnings", [])
    print(f"\nWarnings: {len(warnings)}")
    for warning in warnings:
        print(f"  - {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default=None, help="openai | anthropic | mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None,
                        help="e.g. https://api.groq.com/openai/v1")
    parser.add_argument("--fault", default=None, choices=FAULT_MODES,
                        help="corrupt the first supplier's response, for the demo")
    parser.add_argument("--out", default=None, help="write the run JSON here")
    parser.add_argument("--db", default=None, help="override the SQLite path")
    parser.add_argument("--trace", action="store_true", help="print the agent trace")
    args = parser.parse_args()

    db_path = args.db or str(config.db_path())
    db.init_db(db_path)

    suppliers = sample_suppliers()
    if len(suppliers) < config.MIN_SUPPLIERS:
        print(f"Need at least {config.MIN_SUPPLIERS} supplier PDFs in "
              f"{config.SAMPLE_PDF_DIR}. Run scripts/generate_sample_pdfs.py first.",
              file=sys.stderr)
        return 1

    def on_step(entry: dict) -> None:
        marker = {"ok": "  ", "warn": " !", "error": " x"}.get(entry["status"], "  ")
        print(f"{marker} {entry['step']:<22}{entry['detail']}")

    print(f"Evaluating {len(suppliers)} suppliers: "
          f"{', '.join(s['supplier_name'] for s in suppliers)}\n")

    result = orchestrator.run_evaluation(
        suppliers, provider=args.provider, model=args.model,
        base_url=args.base_url, fault=args.fault, db_path=db_path,
        on_step=on_step,
    )

    print_leaderboard(result)

    if args.trace:
        print("\nAgent trace:")
        for entry in result["agent_trace"]:
            print(f"  [{entry['status']:<5}] {entry['step']:<22}{entry['detail']}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\nwrote {out_path} ({out_path.stat().st_size:,} bytes)")

    if result["status"] == "FAILED":
        print(f"\nRUN FAILED: {result.get('error')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
