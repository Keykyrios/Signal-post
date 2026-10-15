"""Command line: python -m signalpost <command>."""

import argparse
import json
import os
import sys

from . import agent, discover as discover_mod, runner
from .http import Client


def main(argv=None):
    parser = argparse.ArgumentParser(prog="signalpost", description="Norwegian company profile agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="build or refresh profiles for a list of organisation numbers")
    run.add_argument("--input", required=True, help="text file, one organisation number per line")
    run.add_argument("--out", default="out", help="output folder (default: out)")
    run.add_argument("--workers", type=int, default=6)
    run.add_argument("--max-requests", type=int, default=1800)
    run.add_argument("--max-minutes", type=float, default=40)
    run.add_argument("--depth", type=int, choices=(1, 2, 3), default=None,
                     help="1 entity only, 2 plus accounts, 3 plus roles and sub-units (default: fit the request budget)")
    run.add_argument("--skip-fresh-hours", type=float, default=0,
                     help="reuse profiles checked within this many hours (default 0: always refresh)")

    disc = sub.add_parser("discover", help="pick organisation numbers from the register")
    disc.add_argument("--n", type=int, default=1000)
    disc.add_argument("--out", default="companies.txt")
    disc.add_argument("--seed", type=int, default=2026)

    every = sub.add_parser("all", help="discover companies, build profiles, then open the viewer")
    every.add_argument("--n", type=int, default=1000)
    every.add_argument("--out", default="out")
    every.add_argument("--port", type=int, default=8000)
    every.add_argument("--no-serve", action="store_true")

    srv = sub.add_parser("serve", help="open the React viewer on a local port")
    srv.add_argument("--out", default="out")
    srv.add_argument("--port", type=int, default=8000)

    one = sub.add_parser("one", help="print one profile as JSON")
    one.add_argument("orgnr")

    args = parser.parse_args(argv)

    if args.cmd == "discover":
        numbers = discover_mod.discover(args.n, seed=args.seed)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write("\n".join(numbers) + "\n")
        print(f"Wrote {len(numbers)} organisation numbers to {args.out}")
        return 0

    if args.cmd == "run":
        numbers = runner.read_numbers(args.input)
        if not numbers:
            print("No organisation numbers found in the input file.", file=sys.stderr)
            return 2
        print(f"Building {len(numbers)} profiles into {args.out}/")
        _, report = runner.run(numbers, args.out, workers=args.workers,
                               max_requests=args.max_requests,
                               max_seconds=int(args.max_minutes * 60),
                               skip_fresh_hours=args.skip_fresh_hours, depth=args.depth)
        print(json.dumps(report, indent=2))
        print(f"Run: python -m signalpost serve --out {args.out}")
        return 0

    if args.cmd == "all":
        numbers = discover_mod.discover(args.n, seed=2026)
        os.makedirs(args.out, exist_ok=True)
        listing = os.path.join(args.out, "companies.txt")
        with open(listing, "w", encoding="utf-8") as handle:
            handle.write("\n".join(numbers) + "\n")
        _, report = runner.run(numbers, args.out)
        print(json.dumps(report, indent=2))
        if not args.no_serve:
            from . import serve as serve_mod
            serve_mod.serve(args.out, args.port)
        return 0

    if args.cmd == "serve":
        from . import serve as serve_mod
        serve_mod.serve(args.out, args.port)
        return 0

    if args.cmd == "one":
        profile = agent.build_profile(Client(max_requests=10), args.orgnr)
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
