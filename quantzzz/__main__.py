"""Quantzzz CLI.

Usage:
    python -m quantzzz init-db
    python -m quantzzz refresh-data [--desk equity|biotech|all]
    python -m quantzzz research --desk equity --iterations 50
    python -m quantzzz trade --fund equity
    python -m quantzzz run [--cycles N] [--interval-s 900]
    python -m quantzzz dashboard
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from .config import PROJECT_ROOT, load_config
from .db import get_conn, init_schema


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="quantzzz")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create the SQLite schema")

    p_refresh = sub.add_parser("refresh-data", help="refresh snapshots/caches (budget-aware)")
    p_refresh.add_argument("--desk", default="all", choices=["equity", "biotech", "all"])

    p_research = sub.add_parser("research", help="run a research desk loop")
    p_research.add_argument("--desk", required=True, choices=["equity", "biotech"])
    p_research.add_argument("--iterations", type=int, default=50)

    p_trade = sub.add_parser("trade", help="run one trader session for a fund")
    p_trade.add_argument("--fund", required=True, choices=["equity", "biotech"])

    p_replay = sub.add_parser("replay", help="replay a trader over historical dates")
    p_replay.add_argument("--fund", required=True, choices=["equity", "biotech"])
    p_replay.add_argument("--lookback-days", type=int, default=180)
    p_replay.add_argument("--step-days", type=int, default=3)

    p_run = sub.add_parser("run", help="continuous orchestrator loop")
    p_run.add_argument("--cycles", type=int, default=0, help="0 = run forever")
    p_run.add_argument("--interval-s", type=int, default=900)
    p_run.add_argument("--research-iterations", type=int, default=25)

    sub.add_parser("dashboard", help="launch the Streamlit dashboards")

    args = p.parse_args(argv)
    cfg = load_config()

    if args.cmd == "init-db":
        seed = PROJECT_ROOT / "data" / "seed.db"
        if not cfg.db_path.exists() and seed.exists():
            import shutil
            shutil.copy(seed, cfg.db_path)
            print(f"bootstrapped from committed seed (strategies + track record)")
        conn = get_conn(cfg.db_path)
        init_schema(conn)
        print(f"schema ready at {cfg.db_path}")
        return 0

    if args.cmd == "refresh-data":
        from .data.refresh import refresh_data
        refresh_data(cfg, desk=args.desk)
        return 0

    if args.cmd == "research":
        from .research.loop import ResearchDesk
        desk = ResearchDesk.build(cfg, args.desk)
        result = desk.run(args.iterations)
        print(result.summary())
        return 0

    if args.cmd == "trade":
        from .trading.trader import TraderAgent
        agent = TraderAgent.build(cfg, args.fund)
        report = agent.session()
        print(report)
        return 0

    if args.cmd == "replay":
        from .orchestrator import replay
        print(replay(cfg, args.fund, args.lookback_days, args.step_days))
        return 0

    if args.cmd == "run":
        from .orchestrator import run_loop
        run_loop(cfg, cycles=args.cycles, interval_s=args.interval_s,
                 research_iterations=args.research_iterations)
        return 0

    if args.cmd == "dashboard":
        app = PROJECT_ROOT / "dashboards" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
