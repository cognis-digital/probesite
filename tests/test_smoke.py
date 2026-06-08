"""Smoke tests for PROBESITE. No network is used: run_check is stubbed."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probesite import (  # noqa: E402
    TOOL_NAME,
    TOOL_VERSION,
    Check,
    ProbeResult,
    load_checks,
    run_checks,
    summarize,
    to_prometheus,
)
from probesite.core import evaluate, UP, DOWN, DEGRADED  # noqa: E402
from probesite import cli  # noqa: E402


CHECK_JSON = json.dumps(
    {
        "checks": [
            {"name": "home", "target": "https://x.test/", "expect_status": 200,
             "expect_substring": "ok", "max_latency_ms": 500},
            {"name": "port", "target": "tcp://x.test:5432"},
        ]
    }
)


def test_metadata():
    assert TOOL_NAME == "probesite"
    assert TOOL_VERSION.count(".") == 2


def test_load_checks_parses_and_infers_kind():
    checks = load_checks(CHECK_JSON)
    assert [c.name for c in checks] == ["home", "port"]
    assert checks[0].kind == "http"
    assert checks[1].kind == "tcp"  # inferred from tcp:// scheme


def test_load_checks_rejects_duplicates():
    dupe = json.dumps({"checks": [
        {"name": "a", "target": "https://x/"},
        {"name": "a", "target": "https://y/"},
    ]})
    with pytest.raises(ValueError):
        load_checks(dupe)


def test_load_checks_rejects_empty():
    with pytest.raises(ValueError):
        load_checks("[]")


def test_evaluate_status_mismatch():
    c = Check(name="n", target="https://x/", expect_status=200)
    failures = evaluate(c, 503, "", 10.0)
    assert failures and "503" in failures[0]


def test_evaluate_substring_and_latency():
    c = Check(name="n", target="https://x/", expect_status=200,
              expect_substring="hello", max_latency_ms=50)
    fails = evaluate(c, 200, "goodbye", 90.0)
    assert len(fails) == 2  # missing substring + latency budget blown


def test_evaluate_all_pass():
    c = Check(name="n", target="https://x/", expect_status=200,
              expect_substring="hi", max_latency_ms=100)
    assert evaluate(c, 200, "hi there", 40.0) == []


def _fake_runner(state_by_name):
    def runner(check):
        state = state_by_name[check.name]
        return ProbeResult(
            name=check.name, target=check.target, kind=check.kind,
            state=state, up=(state == UP), latency_ms=12.5,
            status_code=200 if state != DOWN else None,
            error="conn refused" if state == DOWN else None,
            failed_assertions=["status 500 != expected 200"] if state == DEGRADED else [],
        )
    return runner


def test_run_checks_with_injected_runner():
    checks = load_checks(CHECK_JSON)
    results = run_checks(checks, runner=_fake_runner({"home": UP, "port": DOWN}))
    summary = summarize(results)
    assert summary["total"] == 2
    assert summary["up"] == 1
    assert summary["down"] == 1
    assert summary["healthy"] is False
    assert summary["availability"] == 0.5


def test_summarize_all_up_is_healthy():
    checks = load_checks(CHECK_JSON)
    results = run_checks(checks, runner=_fake_runner({"home": UP, "port": UP}))
    assert summarize(results)["healthy"] is True


def test_prometheus_export_format():
    checks = load_checks(CHECK_JSON)
    results = run_checks(checks, runner=_fake_runner({"home": UP, "port": DEGRADED}))
    text = to_prometheus(results)
    assert "# TYPE probesite_up gauge" in text
    assert 'probesite_up{name="home",kind="http",state="up"} 1' in text
    assert "probesite_latency_ms{" in text
    assert "probesite_availability " in text
    # every metric line is well-formed (no trailing label braces issues)
    assert text.endswith("\n")


def test_cli_run_json_exit_codes(tmp_path, monkeypatch, capsys):
    cf = tmp_path / "checks.json"
    cf.write_text(CHECK_JSON, encoding="utf-8")
    monkeypatch.setattr(cli, "run_checks",
                        lambda checks: run_checks(checks, runner=_fake_runner({"home": UP, "port": DOWN})))
    rc = cli.main(["run", str(cf), "--format", "json"])
    assert rc == 1  # something down -> non-zero
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["down"] == 1
    assert len(payload["results"]) == 2


def test_cli_run_healthy_exit_zero(tmp_path, monkeypatch):
    cf = tmp_path / "checks.json"
    cf.write_text(CHECK_JSON, encoding="utf-8")
    monkeypatch.setattr(cli, "run_checks",
                        lambda checks: run_checks(checks, runner=_fake_runner({"home": UP, "port": UP})))
    assert cli.main(["run", str(cf)]) == 0


def test_cli_missing_file_exit_two(tmp_path):
    assert cli.main(["run", str(tmp_path / "nope.json")]) == 2


def test_cli_prometheus_output(tmp_path, monkeypatch, capsys):
    cf = tmp_path / "checks.json"
    cf.write_text(CHECK_JSON, encoding="utf-8")
    monkeypatch.setattr(cli, "run_checks",
                        lambda checks: run_checks(checks, runner=_fake_runner({"home": UP, "port": UP})))
    cli.main(["run", str(cf), "--prometheus"])
    assert "probesite_up{" in capsys.readouterr().out
