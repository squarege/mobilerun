"""Build a compact multi-broker inspection report from local run evidence."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Iterable


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "journal.jsonl"
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            result.append(event)
    return result


def _column(events: list[dict[str, Any]], event_name: str, phase: str | None = None) -> str:
    matches = [event for event in events if event.get("event") == event_name]
    if phase is not None:
        matches = [event for event in matches if event.get("phase") == phase]
    if not matches:
        return "—"
    return "通过" if all(event.get("verified", event.get("selected", False)) for event in matches) else "失败"


def _funds(events: list[dict[str, Any]]) -> tuple[str, list[str]]:
    checks = [event for event in events if event.get("event") == "money_verification"]
    if not checks:
        return "—", []
    notes = []
    for event in checks:
        if event.get("verified"):
            continue
        calculated = event.get("calculated_value")
        target = event.get("target_value")
        difference = event.get("difference")
        label = event.get("label") or "资金核算"
        notes.append(f"{label}: 可用+总市值={calculated}, 总资产={target}, 差值={difference}")
    return ("通过" if all(event.get("verified") for event in checks) else "警告"), notes


def _status_evidence(events: list[dict[str, Any]], event_name: str, phase: str | None = None) -> str:
    matches = [event for event in events if event.get("event") == event_name]
    if phase is not None:
        matches = [event for event in matches if event.get("phase") == phase]
    observed = []
    for event in matches:
        observed.extend(str(value) for value in event.get("observed_statuses") or [])
    if observed:
        return f"；观察到状态：{'、'.join(dict.fromkeys(observed))}"
    return ""


def _abnormal_notes(
    events: list[dict[str, Any]],
    connectivity: str,
    route: str,
    funds: str,
    order: str,
    cancel: str,
    result_status: str | None,
) -> list[str]:
    notes: list[str] = []
    if connectivity != "通过":
        notes.append(f"站点连通性：{connectivity}{_status_evidence(events, 'broker_session')}")
    if route in {"失败", "—"}:
        notes.append(f"登录到 KSGT：{route}{_status_evidence(events, 'order_status_verification', 'route')}")
    if funds == "警告":
        _, fund_notes = _funds(events)
        notes.extend(fund_notes)
    if order != "通过":
        notes.append(f"下单状态：{order}{_status_evidence(events, 'order_status_verification', 'pending')}")
    if cancel != "通过":
        notes.append(f"撤单状态：{cancel}{_status_evidence(events, 'order_status_verification', 'cancelled')}")
    if result_status not in {None, "MACRO_SUCCESS", "SUCCESS"}:
        notes.append(f"运行状态：{result_status}")
    return notes


def _route(events: list[dict[str, Any]]) -> str:
    route_events = [event for event in events if event.get("event") == "order_status_verification" and event.get("phase") in {"route", "pending"}]
    if not route_events:
        return "—"
    observed = " ".join(" ".join(event.get("observed_statuses") or []) for event in route_events)
    if "KSGT" in observed.upper() or "快速" in observed:
        return "是"
    if "已申报" in observed and "未报" not in observed:
        return "是"
    if "集中" in observed or "未报" in observed:
        return "否"
    return "通过" if all(event.get("verified") for event in route_events) else "失败"


def build_audit_row(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest = _read_json(run_dir / "manifest.json", {})
    result = _read_json(run_dir / "result.json", {})
    events = _events(run_dir)
    parameters = manifest.get("parameters") or {}
    broker_name = parameters.get("broker_name") or parameters.get("broker_id") or manifest.get("workflow_id", "—")
    funds, _ = _funds(events)
    connectivity = _column(events, "broker_session")
    order = _column(events, "order_status_verification", "pending")
    cancel = _column(events, "order_status_verification", "cancelled")
    route = _route(events)
    result_status = result.get("status")
    notes = _abnormal_notes(events, connectivity, route, funds, order, cancel, result_status)
    if result_status in {"INFRASTRUCTURE_ERROR", "BLOCKED"}:
        conclusion = "失败"
    elif any(value == "失败" for value in (connectivity, funds, order, cancel)):
        conclusion = "失败"
    elif any(value == "警告" for value in (funds,)):
        conclusion = "警告"
    elif all(value in {"通过", "是"} for value in (connectivity, funds, order, cancel)):
        conclusion = "PASS"
    else:
        conclusion = "—"
    return {
        "broker": broker_name,
        "connectivity": connectivity,
        "ksgt": route,
        "funds": funds,
        "order": order,
        "cancel": cancel,
        "conclusion": conclusion,
        "notes": notes,
        "run_id": manifest.get("run_id", run_dir.name),
        "run_dir": str(run_dir),
        "status": result_status,
    }


def collect_audit_rows(workflows_root: str | Path, refs: Iterable[tuple[str, str | None]]) -> list[dict[str, Any]]:
    root = Path(workflows_root)
    rows = []
    for workflow_id, run_id in refs:
        runs_dir = root / workflow_id / "runs"
        if run_id:
            candidates = [runs_dir / run_id]
        else:
            candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir()) if runs_dir.exists() else []
            candidates = candidates[-1:]
        for run_dir in candidates:
            if run_dir.is_dir():
                rows.append(build_audit_row(run_dir))
    return rows


def generate_audit_report(rows: list[dict[str, Any]], output: str | Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(row["conclusion"] == "PASS" for row in rows)
    failed = sum(row["conclusion"] == "失败" for row in rows)
    table_rows = []
    notes = []
    for row in rows:
        table_rows.append("<tr>" + "".join(f"<td class='status-{html.escape(str(row[key])).lower()}'>{html.escape(str(row[key]))}</td>" for key in ("broker", "connectivity", "ksgt", "funds", "order", "cancel", "conclusion")) + "</tr>")
        notes.extend(f"{row['broker']}：{note}" for note in row.get("notes", []))
    note_html = "".join(f"<li>{html.escape(note)}</li>" for note in notes) or "<li>无异常记录</li>"
    content = f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>券商巡检汇总</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:32px;color:#222}}h1{{font-size:24px;border-bottom:1px solid #777;padding-bottom:8px}}.summary{{font-size:18px;margin:12px 0 20px}}table{{border-collapse:collapse;width:100%;font-size:16px}}th,td{{border-bottom:1px solid #ddd;padding:9px 12px;text-align:left}}th{{font-weight:500}}td{{color:#333}}.status-pass,.status-通过,.status-是{{color:#16803a}}.status-警告{{color:#b36b00}}.status-失败{{color:#c62828}}.status-—{{color:#777}}ul{{padding-left:24px}}
</style></head><body><h1>券商巡检汇总</h1>
<div class='summary'>通过 {passed} / 失败 {failed}（共 {len(rows)} 家券商）</div>
<table><thead><tr><th>券商</th><th>站点连通性</th><th>登录到 KSGT</th><th>资金查询</th><th>下单</th><th>撤单</th><th>结论</th></tr></thead>
<tbody>{''.join(table_rows) or '<tr><td colspan="7">没有运行记录</td></tr>'}</tbody></table>
<h3>备注</h3><ul>{note_html}</ul></body></html>"""
    output.write_text(content, encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps({"passed": passed, "failed": failed, "total": len(rows), "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
