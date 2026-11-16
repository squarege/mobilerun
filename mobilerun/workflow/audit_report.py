"""Build a compact multi-broker inspection report from local run evidence."""

from __future__ import annotations

import base64
import html
import json
import mimetypes
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
        observed.extend(str(value) for value in event.get("observed_candidates") or [])
        observed.extend(str(value) for value in event.get("observed_statuses") or [])
    if observed:
        return f"；观察到状态：{'、'.join(dict.fromkeys(observed))}"
    return ""


def _evidence_screenshots(run_dir: Path, events: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    actions: dict[int, dict[str, Any]] = {}
    for event in events:
        if event.get("event") != "step" or not isinstance(event.get("action"), dict):
            continue
        index = event.get("index")
        if isinstance(index, int):
            actions[index] = event["action"]
    evidence: dict[str, list[dict[str, str]]] = {"funds": [], "order": [], "cancel": [], "interruption": []}
    labels = {
        "funds_pre": ("资金查询（下单前）", "funds"),
        "funds_post": ("资金查询（撤单后）", "funds"),
        "order": ("下单后委托页面", "order"),
        "cancel": ("撤单后状态页面", "cancel"),
    }
    for event in events:
        if event.get("event") == "interruption" and event.get("screenshot_path"):
            relative_path = str(event["screenshot_path"])
            if (run_dir / relative_path).is_file():
                evidence["interruption"].append({"label": "中断时截图", "path": relative_path})
            continue
        if event.get("event") != "observation" or event.get("phase") != "post":
            continue
        action = actions.get(event.get("index"), {})
        role = action.get("evidence_role")
        if role not in labels or not event.get("screenshot_path"):
            continue
        label, category = labels[role]
        relative_path = str(event["screenshot_path"])
        if not (run_dir / relative_path).is_file():
            continue
        if any(item["path"] == relative_path for item in evidence[category]):
            continue
        evidence[category].append({"label": label, "path": relative_path})
    return evidence


def _screenshot_data_uri(run_dir: Path, relative_path: str) -> str | None:
    screenshot = (run_dir / relative_path).resolve()
    try:
        screenshot.relative_to(run_dir.resolve())
    except ValueError:
        return None
    if not screenshot.is_file():
        return None
    mime_type = mimetypes.guess_type(screenshot.name)[0] or "image/png"
    encoded = base64.b64encode(screenshot.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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
    price_checks = [event for event in events if event.get("event") == "node_text_verification"]
    for event in price_checks:
        if not event.get("verified"):
            notes.append(
                f"价格核验失败：下限价={event.get('source_text')}, 委托价={event.get('target_text')}"
            )
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
    evidence = _evidence_screenshots(run_dir, events)
    if result_status in {"INFRASTRUCTURE_ERROR", "BLOCKED", "FAILED"}:
        conclusion = "失败"
    elif result_status == "UNKNOWN_OUTCOME":
        conclusion = "未知"
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
        "evidence": evidence,
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
    warnings = sum(row["conclusion"] == "警告" for row in rows)
    unknown = sum(row["conclusion"] == "未知" for row in rows)
    table_rows = []
    notes = []
    evidence_cards = []
    for row in rows:
        table_rows.append("<tr>" + "".join(f"<td class='status-{html.escape(str(row[key])).lower()}'>{html.escape(str(row[key]))}</td>" for key in ("broker", "connectivity", "ksgt", "funds", "order", "cancel", "conclusion")) + "</tr>")
        notes.extend(f"{row['broker']}：{note}" for note in row.get("notes", []))
        sections = []
        for category, title in (("funds", "资金查询"), ("order", "下单证据"), ("cancel", "撤单证据")):
            images = []
            for item in (row.get("evidence") or {}).get(category, []):
                data_uri = _screenshot_data_uri(Path(row["run_dir"]), item["path"])
                if data_uri:
                    images.append(
                        f"<figure><img src='{data_uri}' alt='{html.escape(item['label'])}'><figcaption>{html.escape(item['label'])}</figcaption></figure>"
                    )
            sections.append(f"<section><h4>{title}</h4><div class='shots'>{''.join(images) or '<span class=muted>无截图</span>'}</div></section>")
        interruption_images = []
        for item in (row.get("evidence") or {}).get("interruption", []):
            data_uri = _screenshot_data_uri(Path(row["run_dir"]), item["path"])
            if data_uri:
                interruption_images.append(
                    f"<figure><img src='{data_uri}' alt='中断时截图'><figcaption>中断时截图</figcaption></figure>"
                )
        if interruption_images:
            sections.append(f"<section><h4>中断时截图</h4><div class='shots'>{''.join(interruption_images)}</div></section>")
        evidence_cards.append(
            f"<article class='broker-card'><h3>{html.escape(str(row['broker']))}</h3><div class='evidence-grid'>{''.join(sections)}</div></article>"
        )
    note_html = "".join(f"<li>{html.escape(note)}</li>" for note in notes) or "<li>无异常记录</li>"
    content = f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>券商巡检汇总</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:32px;color:#222}}h1{{font-size:24px;border-bottom:1px solid #777;padding-bottom:8px}}.summary{{font-size:18px;margin:12px 0 20px}}table{{border-collapse:collapse;width:100%;font-size:16px}}th,td{{border-bottom:1px solid #ddd;padding:9px 12px;text-align:left}}th{{font-weight:500}}td{{color:#333}}.status-pass,.status-通过,.status-是{{color:#16803a}}.status-警告{{color:#b36b00}}.status-失败{{color:#c62828}}.status-未知{{color:#8a4b08}}.status-—{{color:#777}}ul{{padding-left:24px}}.broker-card{{margin-top:28px;border:1px solid #ddd;border-radius:8px;padding:16px}}.evidence-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}.shots{{display:flex;gap:12px;flex-wrap:wrap}}figure{{margin:0;max-width:260px}}figure img{{width:100%;max-height:420px;object-fit:contain;border:1px solid #ddd;border-radius:6px;background:#f6f6f6}}figcaption{{font-size:13px;margin-top:4px;color:#555}}.muted{{color:#777}}
</style></head><body><h1>券商巡检汇总</h1>
<div class='summary'>通过 {passed} / 警告 {warnings} / 失败 {failed} / 未知 {unknown}（共 {len(rows)} 家券商）</div>
<table><thead><tr><th>券商</th><th>站点连通性</th><th>登录到 KSGT</th><th>资金查询</th><th>下单</th><th>撤单</th><th>结论</th></tr></thead>
<tbody>{''.join(table_rows) or '<tr><td colspan="7">没有运行记录</td></tr>'}</tbody></table>
<h2>关键截图证据</h2>{''.join(evidence_cards) or '<p class="muted">没有截图证据</p>'}
<h3>备注</h3><ul>{note_html}</ul></body></html>"""
    output.write_text(content, encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps({"passed": passed, "warnings": warnings, "failed": failed, "unknown": unknown, "total": len(rows), "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
