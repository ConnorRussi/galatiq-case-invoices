"""Offline checks for artifact isolation and safe HTML embedding."""

import json
from pathlib import Path
import runpy


dashboard = runpy.run_path(str(Path(__file__).resolve().parents[1] / "dashboard.py"))


def test_dashboard_keeps_repeated_runs_and_skips_broken_artifacts(tmp_path):
    for name in ("first", "second"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "workflow_result.json").write_text(json.dumps({
            "invoice_id": "SAME", "status": "VALIDATION_DENIED", "ingestion": {}
        }))
    (tmp_path / "workflow_result.json").write_text("{partial")
    data = dashboard["collect_artifacts"](tmp_path)
    assert len(data["runs"]) == 2
    assert len(data["warnings"]) == 1


def test_source_cannot_escape_embedded_json(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    attack = '</script><script>alert("invoice")</script>'
    (logs / "workflow_result.json").write_text(json.dumps({
        "status": "TECHNICAL_FAILURE", "ingestion": {}, "reason": attack
    }))
    output = tmp_path / "dashboard.html"
    dashboard["build_dashboard"](logs, output)
    html = output.read_text(encoding="utf-8")
    assert attack not in html
    embedded = html.split('<script id="data" type="application/json">')[1].split('</script>')[0]
    assert json.loads(embedded)["runs"][0]["result"]["reason"] == attack


def test_missing_logs_produces_empty_dashboard(tmp_path):
    data = dashboard["build_dashboard"](tmp_path / "absent", tmp_path / "dashboard.html")
    assert data["runs"] == []
    assert data["evaluations"] == []
