"""CLI for creating, validating, publishing, and running workflows."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import click

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
