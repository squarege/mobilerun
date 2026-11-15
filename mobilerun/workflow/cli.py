"""CLI for creating, validating, publishing, and running workflows."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import click
import yaml

from mobilerun.workflow.anomalies import AnomalyManager
from mobilerun.workflow.audit_report import collect_audit_rows, generate_audit_report
from mobilerun.workflow.registry import WorkflowRegistry


@click.group()
@click.option("--root", default="workflows", show_default=True, help="Workflow registry directory.")
@click.pass_context
def workflow_cli(ctx: click.Context, root: str):
    """Manage versioned MobileRun workflows."""
    ctx.ensure_object(dict)
    ctx.obj["registry"] = WorkflowRegistry(root)


@workflow_cli.command("import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--id", "workflow_id", required=True)
@click.option("--name", default=None)
@click.option("--parameter", "parameter_specs", multiple=True, help="Parameter name or name=default.")
@click.pass_context
def import_workflow(
    ctx,
    source: Path,
    workflow_id: str,
    name: Optional[str],
    parameter_specs: tuple[str, ...],
):
    """Import a native macro as a reviewable draft workflow."""
    parameters = {}
    for spec in parameter_specs:
        if "=" in spec:
            key, default = spec.split("=", 1)
            parameters[key] = {"default": default}
        else:
            parameters[spec] = {"required": True}
    metadata = ctx.obj["registry"].import_macro(
        source, workflow_id=workflow_id, name=name, parameters=parameters
    )
    click.echo(json.dumps(metadata, ensure_ascii=False, indent=2))


@workflow_cli.command("list")
@click.pass_context
def list_workflows(ctx):
    """List registered workflows."""
    click.echo(json.dumps(ctx.obj["registry"].list(), ensure_ascii=False, indent=2))


@workflow_cli.command("inspect")
@click.argument("workflow_id")
@click.option("--version", type=int, default=None)
@click.pass_context
def inspect_workflow(ctx, workflow_id: str, version: Optional[int]):
    """Inspect workflow metadata and its native macro path."""
    click.echo(json.dumps(ctx.obj["registry"].inspect(workflow_id, version), ensure_ascii=False, indent=2))


@workflow_cli.command("validate")
@click.argument("workflow_id")
@click.option("--version", type=int, default=None)
@click.pass_context
def validate_workflow(ctx, workflow_id: str, version: Optional[int]):
    """Validate a workflow before activation."""
    report = ctx.obj["registry"].validate(workflow_id, version)
    click.echo(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if not report.valid:
        raise click.exceptions.Exit(1)


@workflow_cli.command("activate")
@click.argument("workflow_id")
@click.option("--version", type=int, required=True)
@click.pass_context
def activate_workflow(ctx, workflow_id: str, version: int):
    """Activate a validated workflow version."""
    metadata = ctx.obj["registry"].activate(workflow_id, version=version)
    click.echo(json.dumps(metadata, ensure_ascii=False, indent=2))


@workflow_cli.command("run")
@click.argument("workflow_id")
@click.option("--version", type=int, default=None)
@click.option("--device", default=None)
@click.option("--param", "parameters", multiple=True, help="Workflow parameter as key=value.")
@click.option("--on-divergence", type=click.Choice(["stop", "recover"]), default=None)
@click.option(
    "--allow-draft",
    is_flag=True,
    help="Run an explicitly versioned draft once for real-window validation.",
)
@click.option("--provider", default=None)
@click.option("--model", default=None)
@click.option("--config", "config_path", default=None)
@click.pass_context
def run_workflow(
    ctx,
    workflow_id: str,
    version: Optional[int],
    device: Optional[str],
    parameters: tuple[str, ...],
    on_divergence: Optional[str],
    allow_draft: bool,
    provider: Optional[str],
    model: Optional[str],
    config_path: Optional[str],
):
    """Run a published workflow and print its structured result."""
    params = {}
    for item in parameters:
        if "=" not in item:
            raise click.BadParameter("parameters must use key=value", param_hint="--param")
        key, value = item.split("=", 1)
        params[key] = value
    result = asyncio.run(
        ctx.obj["registry"].run(
            workflow_id,
            version=version,
            device_serial=device,
            params=params,
            on_divergence=on_divergence,
            allow_draft=allow_draft,
            provider=provider,
            model=model,
            config_path=config_path,
        )
    )
    if result.details.get("run_id"):
        try:
            scan = AnomalyManager(ctx.obj["registry"].root).scan()
            result.details.update(
                {
                    "lesson_scan_id": scan["scan_id"],
                    "lessons_path": scan["lessons_path"],
                    "active_lesson_count": scan["active_lesson_count"],
                }
            )
            result_path = Path(result.details["run_dir"]) / "result.json"
            result_path.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            result.details["lesson_refresh_error"] = str(exc)
    click.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    if not result.success:
        raise click.exceptions.Exit(1)


@workflow_cli.command("broker-run")
@click.option("--workflow", "workflow_id", default="broker-daily-inspection", show_default=True)
@click.option("--broker", "broker_id", required=True, help="Local broker profile id.")
@click.option("--profile", "profile_path", type=click.Path(exists=True, path_type=Path), default="config/broker_profiles.yaml", show_default=True)
@click.option("--version", type=int, default=None)
@click.option("--device", required=True)
@click.option("--on-divergence", type=click.Choice(["stop", "recover"]), default="stop", show_default=True)
@click.option("--allow-draft", is_flag=True)
@click.option("--confirm-side-effect", is_flag=True, help="Acknowledge that this run may submit and cancel one order.")
@click.option("--config", "config_path", default=None)
@click.pass_context
def broker_run(ctx, workflow_id, broker_id, profile_path, version, device, on_divergence, allow_draft, confirm_side_effect, config_path):
    """Run the generic inspection workflow with a local broker profile."""
    if not confirm_side_effect:
        raise click.ClickException("This inspection submits one order and cancels it; repeat with --confirm-side-effect.")
    profiles = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile = (profiles.get("brokers") or {}).get(broker_id)
    if not isinstance(profile, dict):
        raise click.ClickException(f"broker profile not found: {broker_id}")
    params = dict(profile)
    params["broker_id"] = broker_id
    result = asyncio.run(ctx.obj["registry"].run(
        workflow_id,
        version=version,
        device_serial=device,
        params=params,
        on_divergence=on_divergence,
        allow_draft=allow_draft,
        config_path=config_path,
    ))
    if result.details.get("run_id"):
        run_id = result.details["run_id"]
        summary_path = Path(result.details["run_dir"]) / "audit-summary.html"
        rows = collect_audit_rows(ctx.obj["registry"].root, [(workflow_id, run_id)])
        generate_audit_report(rows, summary_path)
        result.details["audit_summary_path"] = str(summary_path)
        result.details["audit_summary_json"] = str(summary_path.with_suffix(".json"))
        Path(result.details["run_dir"], "result.json").write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    click.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    if not result.success:
        raise click.exceptions.Exit(1)


@workflow_cli.command("runs")
@click.argument("workflow_id")
@click.pass_context
def list_runs(ctx, workflow_id: str):
    """List stored run results for a workflow."""
    click.echo(json.dumps(ctx.obj["registry"].runs(workflow_id), ensure_ascii=False, indent=2))


@workflow_cli.command("report")
@click.argument("workflow_id")
@click.option("--run-id", default=None, help="Run directory id; defaults to the latest run.")
@click.option("--output", type=click.Path(), default=None, help="HTML output path.")
@click.pass_context
def report_workflow(ctx, workflow_id: str, run_id: Optional[str], output: Optional[str]):
    """Generate an HTML timeline for a workflow run."""
    report = ctx.obj["registry"].report(workflow_id, run_id=run_id, output=output)
    click.echo(str(report))


@workflow_cli.command("audit-report")
@click.option("--workflow", "workflow_ids", multiple=True, required=True, help="Workflow ID; latest run is used unless --run is supplied.")
@click.option("--run", "run_refs", multiple=True, help="Specific run as workflow-id:run-id; repeat for multiple brokers.")
@click.option("--output", type=click.Path(), default="runs/audit-summary.html", show_default=True)
@click.pass_context
def audit_report(ctx, workflow_ids, run_refs, output):
    """Generate a compact multi-broker inspection summary."""
    refs = []
    if run_refs:
        for ref in run_refs:
            if ":" not in ref:
                raise click.BadParameter("--run must use workflow-id:run-id")
            refs.append(tuple(ref.split(":", 1)))
    else:
        refs = [(workflow_id, None) for workflow_id in workflow_ids]
    rows = collect_audit_rows(ctx.obj["registry"].root, refs)
    report = generate_audit_report(rows, output)
    click.echo(json.dumps({"report": str(report), "json": str(report.with_suffix('.json')), "rows": rows}, ensure_ascii=False, indent=2))


@workflow_cli.command("scan")
@click.option("--workflow", "workflow_id", default=None, help="Limit the scan to one workflow.")
@click.option("--version", type=int, default=None, help="Limit the scan to one workflow version.")
@click.option("--run-id", default=None, help="Limit the scan to one run.")
@click.option("--since", default=None, help="Only scan runs started at or after an ISO timestamp.")
@click.option("--status", type=click.Choice(["open", "triaged", "repair_planned", "repair_activated", "repaired", "dismissed", "false_positive"]), default=None, help="When listing, show only this status.")
@click.option("--list-only", is_flag=True, help="Show the persisted anomaly index without scanning again.")
@click.option("--set-status", "status_updates", multiple=True, help="Set anomaly status as anomaly-id=status.")
@click.pass_context
def scan_workflow(ctx, workflow_id, version, run_id, since, status, list_only, status_updates):
    """Scan local workflow run evidence for anomalies."""
    manager = AnomalyManager(ctx.obj["registry"].root)
    if list_only:
        anomalies = manager.list_anomalies(status)
        click.echo(json.dumps({"anomaly_count": len(anomalies), "anomalies": anomalies}, ensure_ascii=False, indent=2))
        return
    result = manager.scan(
        workflow_id=workflow_id,
        version=version,
        run_id=run_id,
        since=since,
        set_status=list(status_updates),
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@workflow_cli.command("repair")
@click.argument("anomaly_id")
@click.option("--ai", is_flag=True, help="Run AI triage; static evidence triage is used otherwise.")
@click.option("--provider", default=None, help="Explicit AI provider; requires --model.")
@click.option("--model", default=None, help="Explicit AI model; requires --provider.")
@click.option("--config", "config_path", default=None, help="Configuration used when loading the default AI profile.")
@click.option("--with-screenshots", is_flag=True, help="Send one locally referenced screenshot to the AI triage model.")
@click.option("--create-draft", is_flag=True, help="Apply the reviewed plan to a new draft version.")
@click.pass_context
def repair_workflow(ctx, anomaly_id, ai, provider, model, config_path, with_screenshots, create_draft):
    """Triage an anomaly and optionally create a reviewable repair draft."""
    manager = AnomalyManager(ctx.obj["registry"].root)
    plan = manager.repair(
        anomaly_id,
        ai=ai,
        provider=provider,
        model=model,
        config_path=config_path,
        with_screenshots=with_screenshots,
    )
    response: dict = {"plan": plan}
    if create_draft:
        if plan["status"] != "pending_review":
            raise click.ClickException("a pending_review repair plan is required before creating a draft")
        applied = manager.apply_plan(plan["plan_id"], ctx.obj["registry"])
        response = applied
    click.echo(json.dumps(response, ensure_ascii=False, indent=2))
