"""Build a standalone, read-only HTML snapshot of saved workflow artifacts."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def collect_artifacts(logs: Path) -> dict:
    data = {"runs": [], "evaluations": [], "warnings": []}
    if not logs.exists():
        return data
    for path in sorted(logs.rglob("*.json")):
        if path.name not in {"workflow_result.json", "summary.json"}:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            relative = path.relative_to(logs).as_posix()
            if path.name == "workflow_result.json":
                if not isinstance(value.get("ingestion"), dict) or not value.get("status"):
                    raise ValueError("Missing workflow status or ingestion")
                data["runs"].append({"id": relative, "saved": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc).isoformat(), "result": value})
            elif value.get("suite") == "workflow":
                data["evaluations"].append({"id": relative, "summary": value})
        except (OSError, ValueError) as exc:
            data["warnings"].append(f"Skipped {path.relative_to(logs)}: {exc}")
    data["runs"].sort(key=lambda item: item["saved"], reverse=True)
    data["evaluations"].sort(key=lambda item: item["summary"].get("started_at", ""), reverse=True)
    return data


def build_dashboard(logs: Path, output: Path) -> dict:
    data = collect_artifacts(logs)
    data["generated"] = datetime.now(timezone.utc).isoformat()
    # JSON is embedded as inert data. Escape HTML delimiters even inside strings.
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(
        ">", "\\u003e").replace("&", "\\u0026")
    template = (ROOT / "dashboard_template.html").read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__DASHBOARD_DATA__", payload), encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs-root", type=Path, default=ROOT / "logs")
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "dashboard.html")
    args = parser.parse_args()
    data = build_dashboard(args.logs_root, args.output)
    print(f"Dashboard: {args.output.resolve()}")
    print(f"{len(data['runs'])} saved runs; {len(data['evaluations'])} workflow evaluations")
    for warning in data["warnings"]:
        print(warning)


if __name__ == "__main__":
    main()
