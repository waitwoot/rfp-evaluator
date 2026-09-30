#!/usr/bin/env python3
"""Create the SQLite database and seed the default evaluation criteria.

    python scripts/init_db.py            # create if absent, seed if empty
    python scripts/init_db.py --reset    # restore the five default criteria
    python scripts/init_db.py --force    # delete the DB file and start over
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfp import config, db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true",
                        help="restore the default criteria (runs are kept)")
    parser.add_argument("--force", action="store_true",
                        help="delete the database file first (destroys all runs)")
    parser.add_argument("--db", default=None, help="override the database path")
    args = parser.parse_args()

    target = Path(args.db).expanduser().resolve() if args.db else config.db_path()

    if args.force and target.exists():
        target.unlink()
        print(f"deleted {target}")

    db.init_db(target)
    if args.reset:
        db.reset_criteria(target)
        print("criteria reset to defaults")

    criteria = db.load_criteria(target, active_only=False)
    total = db.active_weight_total(criteria)

    print(f"database : {target}")
    print(f"criteria : {len(criteria)}\n")
    print(f"{'ID':<4}{'Criterion':<26}{'Weight':>8}{'Max':>6}  Active")
    print("-" * 52)
    for c in criteria:
        print(f"{c.criterion_id:<4}{c.name:<26}{c.weight:>7g}%{c.max_score:>6g}"
              f"{'   yes' if c.is_active else '    no'}")
    print("-" * 52)
    print(f"{'':<30}{total:>7g}%")

    ok = abs(total - config.WEIGHT_TOTAL) <= config.WEIGHT_TOLERANCE
    print(f"\n{'OK' if ok else 'FAIL'}: active weights total {total:g}% "
          f"(must be {config.WEIGHT_TOTAL:g}%)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
