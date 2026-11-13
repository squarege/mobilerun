"""CLI for creating, validating, publishing, and running workflows."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import click

from mobilerun.workflow.anomalies import AnomalyManager
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
            provider=provider,
            model=model,
            config_path=config_path,
        )
    )
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
