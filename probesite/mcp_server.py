"""PROBESITE MCP server -- exposes run_checks() as an MCP tool for Cognis.Studio."""
from __future__ import annotations

import json

from probesite.core import load_checks, run_checks, summarize


def _to_json(checks_text: str) -> str:
    """Load, run, and serialize checks to JSON. Raises ValueError on bad input."""
    checks = load_checks(checks_text)
    results = run_checks(checks)
    summary = summarize(results)
    return json.dumps(
        {"summary": summary, "results": [r.as_dict() for r in results]},
        indent=2,
    )


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-probesite[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-probesite[mcp]'")
        return 1
    app = FastMCP("probesite")

    @app.tool()
    def probesite_run(checks_json: str) -> str:
        """Run synthetic uptime checks and return JSON findings.

        Args:
            checks_json: JSON string with a list of check definitions.
        """
        try:
            return _to_json(checks_json)
        except (ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"error": str(exc)})

    app.run()
    return 0
