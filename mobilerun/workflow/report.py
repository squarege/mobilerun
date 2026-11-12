"""Generate a self-contained, reviewable HTML report for a workflow run."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_journal(path: Path) -> list[dict[str, Any]]:
    events = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _relative_asset(run_dir: Path, output_path: Path, value: str | None) -> str | None:
    if not value:
        return None
    candidate = run_dir.parent.parent / value if not Path(value).is_absolute() else Path(value)
    if not candidate.exists():
        candidate = run_dir / value
    if not candidate.exists():
        return None
    return os.path.relpath(candidate, output_path.parent)


def _event_details(event: dict[str, Any]) -> str:
    safe = {key: value for key, value in event.items() if key not in {"timestamp"}}
    return html.escape(json.dumps(safe, ensure_ascii=False, indent=2))


def generate_report(run_dir: str | Path, output: str | Path) -> Path:
    """Write an HTML report and return its path."""
    run_dir = Path(run_dir)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(run_dir / "manifest.json", {})
    result = _read_json(run_dir / "result.json", {})
    events = _read_journal(run_dir / "journal.jsonl")
    proposal_link = None
    if (run_dir / "repair_proposal.json").exists():
        proposal_link = os.path.relpath(run_dir / "repair_proposal.json", output_path.parent)

    rows = []
    for event in events:
        image = _relative_asset(run_dir, output_path, event.get("screenshot_path"))
        image_html = (
            f'<a href="{html.escape(image)}" target="_blank">'
            f'<img class="thumb" src="{html.escape(image)}" alt="step screenshot"></a>'
            if image
            else ""
        )
        step = event.get("step", "")
        label = event.get("status") or event.get("phase") or event.get("event", "")
        action = event.get("action_type", "")
        reason = event.get("reason") or event.get("match_reason") or ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(step))}</td>"
            f"<td><span class=\"badge badge-{html.escape(str(label).lower())}\">{html.escape(str(label))}</span></td>"
            f"<td>{html.escape(str(event.get('event', '')))}</td>"
            f"<td>{html.escape(str(action))}</td>"
            f"<td>{html.escape(str(reason))}</td>"
            f"<td>{image_html}<details><summary>details</summary><pre>{_event_details(event)}</pre></details></td>"
            "</tr>"
        )

    title = f"Mobilerun run {manifest.get('run_id', run_dir.name)}"
    status = result.get("status") or manifest.get("status") or "UNKNOWN"
    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: dark; font-family: ui-sans-serif, system-ui, sans-serif; background:#111827; color:#e5e7eb; }}
body {{ margin:0; padding:28px; }} .wrap {{ max-width:1400px; margin:auto; }}
h1 {{ margin:0 0 8px; }} .muted {{ color:#9ca3af; }}
.summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:22px 0; }}
.card {{ background:#1f2937; border:1px solid #374151; border-radius:10px; padding:14px; }}
.value {{ font-size:1.15rem; font-weight:700; margin-top:5px; overflow-wrap:anywhere; }}
table {{ width:100%; border-collapse:collapse; background:#1f2937; border-radius:10px; overflow:hidden; }}
th,td {{ text-align:left; padding:10px; border-bottom:1px solid #374151; vertical-align:top; }} th {{ color:#9ca3af; font-weight:600; }}
.badge {{ display:inline-block; border-radius:999px; padding:3px 8px; font-size:.8rem; background:#374151; }}
.badge-verified,.badge-macro_success {{ background:#065f46; }} .badge-failed,.badge-unknown_outcome,.badge-blocked {{ background:#991b1b; }}
.badge-started,.badge-pending,.badge-observation {{ background:#1d4ed8; }} .badge-recovery {{ background:#92400e; }}
pre {{ max-width:600px; max-height:300px; overflow:auto; white-space:pre-wrap; color:#cbd5e1; }}
.thumb {{ width:120px; max-height:180px; object-fit:contain; border:1px solid #4b5563; border-radius:6px; display:block; margin-bottom:6px; }}
details summary {{ cursor:pointer; color:#93c5fd; }}
</style></head><body><main class="wrap">
<h1>{html.escape(title)}</h1><div class="muted">Generated from manifest, result, journal, state snapshots, and screenshots.</div>
<section class="summary">
<div class="card">Status<div class="value">{html.escape(str(status))}</div></div>
<div class="card">Workflow<div class="value">{html.escape(str(manifest.get('workflow_id', '')))} v{html.escape(str(manifest.get('workflow_version', '')))}</div></div>
<div class="card">Device<div class="value">{html.escape(str(manifest.get('device') or 'auto'))}</div></div>
<div class="card">Steps<div class="value">{html.escape(str(result.get('steps_completed', 0)))} / {html.escape(str(result.get('total_steps', 0)))}</div></div>
<div class="card">Recoveries<div class="value">{html.escape(str(result.get('recovery_attempts', 0)))}</div></div>
<div class="card">Failure<div class="value">{html.escape(str(result.get('failure_reason') or '—'))}</div></div>
<div class="card">Repair proposal<div class="value">{f'<a href="{html.escape(proposal_link)}">review JSON</a>' if proposal_link else '—'}</div></div>
</section>
<h2>Execution timeline</h2>
<table><thead><tr><th>Step</th><th>Status</th><th>Event</th><th>Action</th><th>Reason</th><th>Evidence</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6">No journal events found.</td></tr>'}</tbody></table>
</main></body></html>
"""
    output_path.write_text(html_text, encoding="utf-8")
    return output_path
