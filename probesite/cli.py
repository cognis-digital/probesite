"""Command-line interface for PROBESITE."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import TOOL_NAME, TOOL_VERSION
from .core import load_checks, run_checks, summarize, to_prometheus


def _render_table(results, summary) -> str:
    rows = [("NAME", "KIND", "STATE", "CODE", "LATENCY_MS", "DETAIL")]
    for r in results:
        detail = r.error or "; ".join(r.failed_assertions) or ""
        rows.append(
            (
                r.name,
                r.kind,
                r.state.upper(),
                "" if r.status_code is None else str(r.status_code),
                f"{r.latency_ms:.1f}",
                detail[:48],
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    for ri, row in enumerate(rows):
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if ri == 0:
            out.append("  ".join("-" * widths[i] for i in range(len(row))))
    out.append("")
    out.append(
        f"{summary['up']}/{summary['total']} up  "
        f"degraded={summary['degraded']}  down={summary['down']}  "
        f"avail={summary['availability']:.2%}  "
        f"avg_latency={summary['avg_latency_ms']:.1f}ms"
    )
    return "\n".join(out)


def _cmd_run(args) -> int:
    path = Path(args.checks)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: check file not found: {path}", file=sys.stderr)
        return 2
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read check file: {exc}", file=sys.stderr)
        return 2
    try:
        checks = load_checks(text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: invalid check file: {exc}", file=sys.stderr)
        return 2

    try:
        results = run_checks(checks)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: probe run failed: {exc}", file=sys.stderr)
        return 1
    summary = summarize(results)

    if args.prometheus:
        sys.stdout.write(to_prometheus(results))
    elif args.format == "json":
        print(
            json.dumps(
                {"summary": summary, "results": [r.as_dict() for r in results]},
                indent=2,
            )
        )
    else:
        print(_render_table(results, summary))

    # Exit non-zero if anything is down or degraded.
    return 0 if summary["healthy"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Synthetic uptime/latency checks exported to Prometheus.",
    )
    parser.add_argument(
        "--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run all checks in a check file.")
    run.add_argument("checks", help="Path to a JSON check file.")
    run.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )
    run.add_argument(
        "--prometheus",
        action="store_true",
        help="Emit Prometheus text-format metrics instead of a report.",
    )
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
