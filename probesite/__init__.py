"""PROBESITE - synthetic uptime checks exported to Prometheus.

Standard-library-only synthetic monitoring. Define HTTP/TCP probes in a JSON
check file, run them, and emit Prometheus text-format metrics or a JSON/table
report.
"""
from .core import (
    Check,
    ProbeResult,
    load_checks,
    run_checks,
    run_check,
    to_prometheus,
    summarize,
)

TOOL_NAME = "probesite"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Check",
    "ProbeResult",
    "load_checks",
    "run_checks",
    "run_check",
    "to_prometheus",
    "summarize",
    "TOOL_NAME",
    "TOOL_VERSION",
]
