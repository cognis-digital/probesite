"""Tests for the hardening added in the cognis-audit/repo-hardening pass.

Covers: input-validation paths, edge cases, and CLI error exits that the
original smoke suite did not exercise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probesite.core import (  # noqa: E402
    Check,
    _validated_timeout,
    _probe_tcp,
    summarize,
    TOOL_NAME,
    TOOL_VERSION,
)
from probesite import cli  # noqa: E402


# ---------------------------------------------------------------------------
# _validated_timeout
# ---------------------------------------------------------------------------

def test_timeout_zero_raises():
    with pytest.raises(ValueError, match="timeout must be > 0"):
        _validated_timeout(0.0)


def test_timeout_negative_raises():
    with pytest.raises(ValueError, match="timeout must be > 0"):
        _validated_timeout(-5.0)


def test_timeout_positive_passes():
    assert _validated_timeout(0.001) == pytest.approx(0.001)
    assert _validated_timeout(30.0) == 30.0


# ---------------------------------------------------------------------------
# Check.from_dict validation
# ---------------------------------------------------------------------------

def test_from_dict_empty_name_raises():
    with pytest.raises(ValueError, match="name.*must not be empty"):
        Check.from_dict({"name": "   ", "target": "https://x/"})


def test_from_dict_empty_target_raises():
    with pytest.raises(ValueError, match="target.*must not be empty"):
        Check.from_dict({"name": "mycheck", "target": "   "})


def test_from_dict_timeout_zero_raises():
    with pytest.raises(ValueError, match="timeout must be > 0"):
        Check.from_dict({"name": "c", "target": "https://x/", "timeout": 0})


def test_from_dict_unsupported_kind_raises():
    with pytest.raises(ValueError, match="unsupported check kind"):
        Check.from_dict({"name": "c", "target": "https://x/", "kind": "ftp"})


def test_from_dict_missing_name_raises():
    with pytest.raises(ValueError, match="requires 'name' and 'target'"):
        Check.from_dict({"target": "https://x/"})


# ---------------------------------------------------------------------------
# _probe_tcp port validation (no network used -- returns error string)
# ---------------------------------------------------------------------------

def test_probe_tcp_port_out_of_range_high():
    check = Check(name="t", target="tcp://localhost:99999", kind="tcp")
    _s, _b, _l, error = _probe_tcp(check)
    assert error is not None
    assert "out of range" in error


def test_probe_tcp_port_zero():
    check = Check(name="t", target="tcp://localhost:0", kind="tcp")
    _s, _b, _l, error = _probe_tcp(check)
    assert error is not None
    assert "out of range" in error


def test_probe_tcp_non_numeric_port():
    check = Check(name="t", target="tcp://localhost:abc", kind="tcp")
    _s, _b, _l, error = _probe_tcp(check)
    assert error is not None
    assert "invalid port" in error


def test_probe_tcp_missing_port():
    check = Check(name="t", target="tcp://localhost", kind="tcp")
    _s, _b, _l, error = _probe_tcp(check)
    assert error is not None
    assert "tcp target must be tcp://host:port" in error


# ---------------------------------------------------------------------------
# summarize edge cases
# ---------------------------------------------------------------------------

def test_summarize_empty_list_no_division_error():
    summary = summarize([])
    assert summary["total"] == 0
    assert summary["availability"] == 0.0
    assert summary["avg_latency_ms"] == 0.0
    assert summary["healthy"] is True  # nothing is down


# ---------------------------------------------------------------------------
# CLI error paths
# ---------------------------------------------------------------------------

def test_cli_malformed_json_exit_two(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json}", encoding="utf-8")
    rc = cli.main(["run", str(bad)])
    assert rc == 2


def test_cli_empty_json_array_exit_two(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    rc = cli.main(["run", str(empty)])
    assert rc == 2


def test_cli_binary_file_exit_two(tmp_path):
    """Binary file that cannot be decoded as UTF-8 -> clean error, not traceback."""
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe binary garbage \x00\x01\x02")
    rc = cli.main(["run", str(binary)])
    assert rc == 2


def test_constants_present():
    assert TOOL_NAME == "probesite"
    assert TOOL_VERSION.count(".") == 2
