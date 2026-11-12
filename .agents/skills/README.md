# Mobilerun repository skills

These skills are maintained with the Mobilerun repository rather than only in the user's global skill directory.

## Skills

- `mobilerun-workflow/`: create, inspect, validate, publish, run, debug, and batch-run workflows.
- `mobilerun-workflow-stabilizer/`: explore a task repeatedly, consolidate a stable workflow, run a final batch, and report strict/supervised pass rates.
- `mobilerun-workflow-runner/`: interactively list workflows, choose a workflow/device/mode/count, execute it, and produce a run report.

The canonical source for repository work is this `.agents/skills/` directory. The copies under `~/.agents/skills/` may be used by the local agent runtime, but should be synchronized from this repository when skill behavior changes.

Keep generated device artifacts, screenshots, credentials, and run logs out of commits unless they are intentionally curated test fixtures.
