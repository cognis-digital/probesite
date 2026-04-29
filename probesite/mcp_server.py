"""PROBESITE MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from probesite.core import scan, to_json

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
    def probesite_scan(target: str) -> str:
        """Synthetic uptime and Playwright checks exported to Prometheus. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
