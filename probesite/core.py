"""Core synthetic-monitoring engine for PROBESITE.

A *check* describes a target to probe (HTTP or TCP) plus optional assertions
(expected status code, substring that must appear in the body, latency budget).
Running a check produces a :class:`ProbeResult` that can be serialized to JSON,
rendered as a table, or exported as Prometheus text-format metrics.

Networking lives entirely in :func:`run_check`; everything else is pure logic
so it can be unit-tested without sockets.
"""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Iterable

# Probe outcome states.
UP = "up"
DOWN = "down"
DEGRADED = "degraded"  # reachable, but an assertion failed


@dataclass
class Check:
    """A single synthetic check definition."""

    name: str
    target: str  # http(s)://host/path  OR  tcp://host:port
    kind: str = "http"  # "http" | "tcp"
    method: str = "GET"
    timeout: float = 10.0
    expect_status: int | None = 200
    expect_substring: str | None = None
    max_latency_ms: float | None = None
    headers: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "Check":
        if not isinstance(raw, dict):
            raise ValueError(f"check must be an object, got {type(raw).__name__}")
        if "name" not in raw or "target" not in raw:
            raise ValueError("each check requires 'name' and 'target'")
        target = str(raw["target"])
        kind = str(raw.get("kind") or _infer_kind(target))
        if kind not in ("http", "tcp"):
            raise ValueError(f"unsupported check kind: {kind!r}")
        return cls(
            name=str(raw["name"]),
            target=target,
            kind=kind,
            method=str(raw.get("method", "GET")).upper(),
            timeout=float(raw.get("timeout", 10.0)),
            expect_status=raw.get("expect_status", 200 if kind == "http" else None),
            expect_substring=raw.get("expect_substring"),
            max_latency_ms=raw.get("max_latency_ms"),
            headers=dict(raw.get("headers", {})),
        )


@dataclass
class ProbeResult:
    """Outcome of running a single :class:`Check`."""

    name: str
    target: str
    kind: str
    state: str
    up: bool
    latency_ms: float
    status_code: int | None = None
    error: str | None = None
    failed_assertions: list = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return asdict(self)


def _infer_kind(target: str) -> str:
    if target.startswith("tcp://"):
        return "tcp"
    return "http"


def load_checks(text: str) -> list[Check]:
    """Parse a JSON check file (a list of checks, or {\"checks\": [...]})."""
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("checks", [])
    if not isinstance(data, list):
        raise ValueError("check file must be a JSON list or {'checks': [...]}")
    checks = [Check.from_dict(item) for item in data]
    if not checks:
        raise ValueError("no checks defined")
    names = [c.name for c in checks]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate check names: {', '.join(sorted(dupes))}")
    return checks


def evaluate(
    check: Check,
    status_code: int | None,
    body: str,
    latency_ms: float,
) -> list[str]:
    """Return a list of human-readable assertion failures (empty == all pass).

    Pure function: no I/O, so it is trivially testable.
    """
    failures: list[str] = []
    if check.expect_status is not None and status_code is not None:
        if status_code != int(check.expect_status):
            failures.append(
                f"status {status_code} != expected {int(check.expect_status)}"
            )
    if check.expect_substring:
        if check.expect_substring not in body:
            failures.append(f"body missing substring {check.expect_substring!r}")
    if check.max_latency_ms is not None:
        if latency_ms > float(check.max_latency_ms):
            failures.append(
                f"latency {latency_ms:.1f}ms > budget {float(check.max_latency_ms):.1f}ms"
            )
    return failures


def _probe_http(check: Check) -> tuple[int | None, str, float, str | None]:
    req = urllib.request.Request(check.target, method=check.method)
    req.add_header("User-Agent", "probesite/1.0")
    for key, value in check.headers.items():
        req.add_header(str(key), str(value))
    ctx = ssl.create_default_context()
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=check.timeout, context=ctx) as resp:
            raw = resp.read(65536)
            latency_ms = (time.perf_counter() - start) * 1000.0
            body = raw.decode("utf-8", "replace")
            return resp.getcode(), body, latency_ms, None
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        try:
            body = exc.read(65536).decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive
            body = ""
        # HTTP errors still gave us a response code; assertions decide up/down.
        return exc.code, body, latency_ms, None
    except (urllib.error.URLError, socket.timeout, OSError, ValueError) as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        reason = getattr(exc, "reason", exc)
        return None, "", latency_ms, str(reason)


def _probe_tcp(check: Check) -> tuple[int | None, str, float, str | None]:
    rest = check.target[len("tcp://"):] if check.target.startswith("tcp://") else check.target
    if ":" not in rest:
        return None, "", 0.0, "tcp target must be tcp://host:port"
    host, _, port_s = rest.partition(":")
    try:
        port = int(port_s)
    except ValueError:
        return None, "", 0.0, f"invalid port {port_s!r}"
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=check.timeout):
            latency_ms = (time.perf_counter() - start) * 1000.0
            return None, "", latency_ms, None
    except (OSError, socket.timeout) as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return None, "", latency_ms, str(exc)


def run_check(check: Check) -> ProbeResult:
    """Execute one check against the network and classify the outcome."""
    if check.kind == "tcp":
        status_code, body, latency_ms, error = _probe_tcp(check)
    else:
        status_code, body, latency_ms, error = _probe_http(check)

    if error is not None:
        return ProbeResult(
            name=check.name,
            target=check.target,
            kind=check.kind,
            state=DOWN,
            up=False,
            latency_ms=round(latency_ms, 3),
            status_code=status_code,
            error=error,
        )

    failures = evaluate(check, status_code, body, latency_ms)
    state = UP if not failures else DEGRADED
    return ProbeResult(
        name=check.name,
        target=check.target,
        kind=check.kind,
        state=state,
        up=(state == UP),
        latency_ms=round(latency_ms, 3),
        status_code=status_code,
        error=None,
        failed_assertions=failures,
    )


def run_checks(
    checks: Iterable[Check],
    runner: Callable[[Check], ProbeResult] = run_check,
) -> list[ProbeResult]:
    """Run every check sequentially. ``runner`` is injectable for tests."""
    return [runner(c) for c in checks]


def summarize(results: list[ProbeResult]) -> dict[str, Any]:
    """Aggregate results into a status summary."""
    total = len(results)
    up = sum(1 for r in results if r.state == UP)
    degraded = sum(1 for r in results if r.state == DEGRADED)
    down = sum(1 for r in results if r.state == DOWN)
    latencies = [r.latency_ms for r in results if r.error is None]
    avg_latency = round(sum(latencies) / len(latencies), 3) if latencies else 0.0
    return {
        "total": total,
        "up": up,
        "degraded": degraded,
        "down": down,
        "availability": round(up / total, 4) if total else 0.0,
        "avg_latency_ms": avg_latency,
        "healthy": (degraded == 0 and down == 0),
    }


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def to_prometheus(results: list[ProbeResult]) -> str:
    """Render results as Prometheus text-format (v0.0.4) metrics."""
    lines: list[str] = []
    lines.append("# HELP probesite_up Whether the check passed (1) or not (0).")
    lines.append("# TYPE probesite_up gauge")
    for r in results:
        lbl = f'name="{_esc(r.name)}",kind="{_esc(r.kind)}",state="{_esc(r.state)}"'
        lines.append(f"probesite_up{{{lbl}}} {1 if r.up else 0}")

    lines.append("# HELP probesite_latency_ms Probe round-trip latency in milliseconds.")
    lines.append("# TYPE probesite_latency_ms gauge")
    for r in results:
        lbl = f'name="{_esc(r.name)}",kind="{_esc(r.kind)}"'
        lines.append(f"probesite_latency_ms{{{lbl}}} {r.latency_ms}")

    lines.append("# HELP probesite_status_code Last observed HTTP status code.")
    lines.append("# TYPE probesite_status_code gauge")
    for r in results:
        if r.status_code is not None:
            lbl = f'name="{_esc(r.name)}"'
            lines.append(f"probesite_status_code{{{lbl}}} {r.status_code}")

    summary = summarize(results)
    lines.append("# HELP probesite_availability Fraction of checks fully up.")
    lines.append("# TYPE probesite_availability gauge")
    lines.append(f"probesite_availability {summary['availability']}")
    return "\n".join(lines) + "\n"
