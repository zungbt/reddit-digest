import argparse
from datetime import date
import functools
import sys

from digest.classify import agy_run
from digest.run import Deps, run


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="python -m digest", description="Reddit Digest CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_run = subparsers.add_parser("run", help="Run daily digest generation")
    parser_run.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Date for digest in YYYY-MM-DD format (default: today)",
    )
    parser_run.add_argument(
        "--reclassify",
        action="store_true",
        help="Reclassify existing digest posts without fetching feeds",
    )

    parser_review = subparsers.add_parser("review", help="Review reject/keep feedback")

    args = parser.parse_args(argv)

    if args.command == "run":
        d = args.date or date.today()
        try:
            deps = Deps(
                run_agy_screen=functools.partial(agy_run, level="low"),
                reclassify=args.reclassify,
            )
        except TypeError:
            try:
                deps = Deps(reclassify=args.reclassify)
            except TypeError:
                deps = Deps()
                if hasattr(deps, "reclassify"):
                    deps.reclassify = args.reclassify
        digest_path = run(today=d, deps=deps)
        print(f"Digest generated: {digest_path}")
        return 0
    elif args.command == "review":
        try:
            from digest.review import review_main
            return review_main()
        except ImportError:
            print("Review command not implemented yet (Task 8).")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
