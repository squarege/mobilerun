---
name: mobilerun-workflow
description: Create, record, modify, validate, publish, optimize, run, debug, and batch-run Mobilerun mobile workflows. Use this skill whenever the user mentions Mobilerun workflows, macros, trajectory recording, Android/iOS device automation, ADB device runs, workflow recovery, replay, multi-device execution, or asks to control a phone through Mobilerun—even if they only ask for a command, a configuration change, or a quick workflow fix. Prefer repository-native Mobilerun workflow commands and produce auditable run results. Requires a Mobilerun repository, Python/uv, ADB for Android, and any provider/device credentials needed by the requested run. Never expose API keys, setup tokens, passwords, or secret values in logs or workflow files.
---

# Mobilerun Workflow Operator

Use this skill to turn a natural-language mobile task into a safe, repeatable, versioned Mobilerun workflow, or to operate an existing workflow. Treat a workflow as a versioned automation artifact with a recorded macro, pre-action state evidence, parameters, policy, validation, activation, and structured run results—not as an unreviewed sequence of taps.

## 1. Establish the execution context

Before changing files or starting a device run:

1. Identify the Mobilerun repository root and read the repository's current workflow docs if present:
   - `docs/workflow-runbook.md`
   - `docs/workflow-gap-analysis.md`
   - `mobilerun/workflow/cli.py`
   - `mobilerun/workflow/registry.py`
   - relevant `mobilerun/macro/` implementation and tests
2. Prefer the repository-local runtime:
   - `uv run mobilerun ...` when `pyproject.toml` and `uv.lock` are present;
   - otherwise the repository's documented virtualenv command.
   Do not silently use a globally installed Mobilerun version when the repository has a newer checkout. Compare `mobilerun --version` and `uv run mobilerun --version` if version drift could affect config or schema.
   Configuration is resolved in this order: an explicit `--config` value, `MOBILERUN_CONFIG`, `config.yaml` in the current project directory, then the user config. Run project commands from the repository root or set `MOBILERUN_CONFIG` explicitly so the modified checkout does not inherit an unrelated global file.
   For Android runs that depend on reliable state observation, use `device.use_tcp: true` and `device.portal_mode: required` in the selected config. If Portal cannot provide state, stop and classify the run as an observation/infrastructure failure. Do not silently accept a UiAutomator fallback when visual or accessibility evidence is required.
3. Discover devices before selecting one:
   ```bash
   adb devices
   uv run mobilerun devices
   ```
   Pass an explicit serial with `--device` for every real run. Mobilerun's normal single-run path does not select one device when several are online.
4. Establish safety boundaries. Confirm the target app, device, environment, success condition, and whether actions have side effects. For payments, trading, deletion, messaging, account changes, or production data, require explicit confirmation immediately before the irreversible action. Prefer a simulator, test account, dry-run, or `--on-divergence stop`.
5. Keep credentials outside source, prompts, macro JSON, logs, screenshots, and reports. Use Mobilerun's credential manager and `type_secret`/`secret_id` actions where applicable. Redact keys in command output and summaries.
6. Keep concrete workflows, run IDs, device-specific traces, screenshots, state dumps, and credentials local. The repository pre-commit hook runs `scripts/check_staged_privacy.py`; stage only generic examples and source changes, then run that check before committing.

## 2. Choose the right operation

| User intent | Operation |
|---|---|
| Explore a new task or produce a one-off result | `mobilerun run` |
| Capture a reliable action sequence | `mobilerun run --save-trajectory action` |
| Inspect or replay an existing recording | `mobilerun macro list` / `mobilerun macro replay` |
| Turn a recording into a reviewed artifact | `mobilerun workflow import` |
| Check a workflow before use | `mobilerun workflow validate` and `inspect` |
| Publish a version | `mobilerun workflow activate` |
| Execute a published workflow | `mobilerun workflow run` |
| Diagnose a run | inspect `result.json`, `journal.jsonl`, `repair_proposal.json`, and `workflow runs` |
| Find recurring execution anomalies | `mobilerun workflow scan` |
| Prepare a reviewed repair | `mobilerun workflow repair <anomaly-id>` |
| Repeat across devices | launch one isolated process per serial with bounded concurrency and per-device logs; do not pretend one Mobilerun run controls a device pool |

If the user asks to “modify the workflow,” do not edit the active version in place. Create or import a new version, validate it, compare the diff, and activate only after review.

## 3. Create a workflow from a task

### 3.1 Explore and record

Use a bounded exploratory run on a named device:

```bash
uv run mobilerun run "<task>" \
  --device <serial> \
  --save-trajectory action
uv run mobilerun macro list
```

If the task has a potentially destructive step, stop before that step and ask for confirmation. A successful exploratory run is evidence, not automatically a published workflow.

### 3.2 Replay the recording without a model

Find the generated trajectory/macro and first test deterministic replay:

```bash
uv run mobilerun macro replay trajectories/<run> --device <serial> --on-mismatch stop
```

Use `--dry-run` when only inspecting actions. Prefer `--on-mismatch stop` while stabilizing a workflow; use `recover` only after recovery behavior is understood and bounded.

### 3.3 Import as a draft

```bash
uv run mobilerun workflow import trajectories/<run> \
  --id <workflow-id> \
  --name "<human-readable name>" \
  --parameter query \
  --parameter environment=staging
```

The imported version is a `draft`. Inspect its metadata and macro path:

```bash
uv run mobilerun workflow inspect <workflow-id>
```

## 4. Modify and optimize safely

A workflow consists of `workflow.json` metadata and a Macro v2 `macro.json`. Preserve the schema and make the smallest change that improves reliability.

### Metadata changes

Review and tune:

- `parameters`: make user-varying values explicit; use `{{parameter}}` placeholders in action values. Replacement is literal—never add Python, shell, or template evaluation.
- `entry_check` and `completion_check`: prefer package checks or a unique accessibility selector; completion must prove the task, not merely that the last tap occurred.
- `policy.on_divergence`: start with `stop`; use `recover` only with a small recovery budget.
- `max_recoveries`, `max_agent_actions_per_recovery`, `max_recovery_seconds`, `state_timeout`, and `state_threshold`: keep recovery bounded and observable.
- `allow_side_effect_retry`: keep false for actions that could duplicate a purchase, order, payment, message, deletion, or submission.
- `auto_publish_repair`: keep false. A repair proposal needs review before becoming a workflow version.

### Macro changes

Prefer, in order:

1. stable selectors with unique accessibility evidence;
2. semantic actions such as `start_app`, `tap_selector`, `input_text`, `wait`, and `type_secret`;
3. pre-action state snapshots that identify the expected screen and app;
4. waits only where the UI genuinely needs stabilization;
5. coordinates only as a last resort, and document why they are safe;
6. short, deterministic paths with explicit post-state checks.

Never remove `pre_state` just to make validation pass. Never replace a secret with its literal value. Never make recovery replay a side-effecting action unless the outcome is known to be safe.

After editing or importing a new version:

```bash
uv run mobilerun workflow validate <workflow-id> --version <N>
uv run mobilerun workflow inspect <workflow-id> --version <N>
```

Fix every validation error. Treat warnings as review items, especially missing matchable state evidence and fixed input values.

## 5. Publish and run

Activate only a validated version:

```bash
uv run mobilerun workflow activate <workflow-id> --version <N>
```

Run it on an explicit device:

```bash
uv run mobilerun workflow run <workflow-id> \
  --version <N> \
  --device <serial> \
  --param query="手机" \
  --param environment=staging \
  --on-divergence stop
```

Use `--on-divergence recover` only when the workflow policy and recovery constraints are appropriate:

```bash
uv run mobilerun workflow run <workflow-id> --device <serial> --on-divergence recover
```

Inspect structured status and history:

```bash
uv run mobilerun workflow runs <workflow-id>
```

For each run, report the workflow/version, device serial, status, completed/total steps, failure reason, journal path, and any repair proposal. Read `result.json` and `journal.jsonl` instead of inferring success from console text.

Each run also writes a local evidence bundle under `workflows/<workflow-id>/runs/<run-id>/` with `manifest.json`, `result.json`, `journal.jsonl`, state snapshots in `artifacts/states/`, screenshots in `artifacts/screenshots/`, and, when recovery diverges, `repair_proposal.json`. Generate the reviewable timeline with:

```bash
uv run mobilerun workflow report <workflow-id> [--run-id <run-id>]
```

The journal records `recovery_start`, `recovery_prompt`, `recovery_llm`, `recovery_action`, and `recovery_state` events. Use those records and the HTML report to explain what context the recovery agent received, which bounded action it tried, whether the failed precondition was re-observed, and why execution resumed or stopped. A repair proposal is a candidate for review only. Import it into a new version and validate it before activation. Never commit the evidence bundle or a report containing a concrete workflow.

## 6. Multi-device execution

A single Mobilerun agent is single-device. ADB may expose many devices, but the standard CLI requires an explicit `--device` and has no built-in device-pool scheduler.

For a temporary fan-out, launch isolated processes with bounded concurrency, separate logs, and one serial per process. Prefer a small cap such as 3–5 before attempting 10 devices because every agent can consume LLM quota and host CPU:

```bash
mkdir -p logs
for serial in $(adb devices | awk '$2=="device"{print $1}'); do
  (
    uv run mobilerun workflow run <workflow-id> \
      --device "$serial" \
      --on-divergence stop \
      >"logs/$serial.log" 2>&1
    echo $? >"logs/$serial.exit"
  ) &
done
wait
```

Do not claim this is a centralized scheduler. It is process-level fan-out. Use unique output paths and inspect each device's result separately. For a durable feature, design a batch orchestrator that owns concurrency, per-device state, cancellation, retries, rate limits, and an aggregate result rather than adding hidden global state to `MobileAgent`.

## 7. Diagnose failures

Classify the failure before changing the workflow:

- **Wrong executable/version**: compare `mobilerun --version` and `uv run mobilerun --version`; use `uv run` for the checkout.
- **Wrong config**: print the resolved config path and use `--config` or `MOBILERUN_CONFIG`; never mix old global config with a newer schema.
- **Portal/UiAutomator fallback**: inspect the selected config for `use_tcp: true` and `portal_mode: required`, then run the repository's device/Portal diagnostics. Treat missing Portal state as an observation/infrastructure failure rather than a model reasoning failure.
- **Device selection**: run `adb devices`; pass `--device <serial>`; check the device is `device`, not `offline` or `unauthorized`.
- **UI divergence**: inspect the last journal state, package/activity, selector evidence, and screenshot; prefer a new recorded version over blind coordinate changes.
- **Unknown outcome after a side effect**: stop. Do not automatically retry. Inspect the app and account state first.
- **LLM/tool protocol failure**: capture the raw response with secrets removed, identify whether the failure is provider transport, native tool calls, XML/DSML markup, or Mobilerun parsing, then add a focused regression test before relaxing a parser.
- **Recovery loop**: check recovery count, action budget, time budget, and whether the same action was retried. Do not increase budgets until the failure mode is understood.

When changing implementation code, use a failing regression test at the parser, replay, registry, or CLI seam that reproduces the exact symptom. Run targeted tests first, then the full suite.

## 8. Anomaly scan and repair

Use the repository-local scanner before proposing workflow changes:

```bash
uv run mobilerun workflow scan
uv run mobilerun workflow scan --workflow <workflow-id> [--version <N>] [--run-id <run-id>]
```

Report a concise table: anomaly ID, workflow/version/run, failed step, type, severity, status, evidence path, and suggested next action. Do not paste raw journals, UI dumps, screenshots, or concrete workflow details into the conversation. Scan and triage products stay in the local ignored `runs/scans/` directory and must never be committed.

For repair planning, use static triage first:

```bash
uv run mobilerun workflow repair <anomaly-id>
```

Ask for explicit user approval before `--ai`, and ask again before `--create-draft`. With screenshots, use `--with-screenshots` only when the user approves sending local UI evidence to the configured model. A repair plan may only insert a wait, back, or unique-selector tap, replace a coordinate tap with a unique selector, or set a package/selector completion check. Never raise budgets, weaken pre-state guards, retry unknown side effects, or invent coordinates.

`--create-draft` creates the next immutable draft version; it does not activate it. Run `workflow validate`, show the changed step and completion check, and let the user explicitly activate and replay on an approved device. Mark the anomaly repaired only after a subsequent `MACRO_SUCCESS` proves the failed step no longer diverges.

## 9. Expected response format

For operational requests, respond with:

```text
## Plan
- device/config/runtime
- workflow operation and safety boundary

## Commands
<exact commands, with secrets redacted>

## Changes
- files or workflow version changed
- parameters/policy/checks changed

## Verification
- validation result
- dry-run/replay/run result
- device and artifact paths

## Risks / next step
- remaining divergence, side effects, rate limits, or human confirmation needed
```

If required information is missing, ask only for the smallest missing piece: device serial(s), workflow id/version, target app, desired success check, or whether the action may have side effects. Do not start a real-device run merely to guess.
