---
name: mobilerun-workflow-stabilizer
description: Build a stable Mobilerun workflow from repeated AI exploration. Use this skill whenever the user asks to create/fix a mobile workflow by having AI run the task several times, learn from failures, consolidate a trajectory into a versioned workflow, run it repeatedly (especially 5 or 10 times), measure pass rate, or produce an execution report. It covers Android/iOS Mobilerun runs, macro/trajectory promotion, recovery validation, workflow versioning, batch execution, and auditable reports. Requires a Mobilerun repository, uv/Python, an explicit device serial, configured model credentials, and the repository-native workflow CLI.
---

# Mobilerun Workflow Stabilizer

Turn an uncertain natural-language mobile task into a versioned workflow that has evidence behind it. The core loop is:

```text
AI exploration runs → failure classification → candidate selection/repair
→ deterministic replay → validate/activate → 10 supervised runs → report
```

A workflow is not stable because an Agent says it succeeded. Stability requires code-side completion checks, run results, and a repeatable batch.

## Completion contract

Do not declare the task complete until all of these are true:

1. At least one bounded natural-language exploration run produced a usable action-level trajectory.
2. Exploration failures were classified and either fixed, made reproducible, or recorded as blockers.
3. A candidate Macro was imported as a draft workflow and validated.
4. The workflow has an explicit completion check that proves the business result.
5. The workflow was activated as a new immutable version; never edit the active version in place.
6. A deterministic baseline was attempted with `--on-divergence stop`.
7. The final batch ran exactly the requested number of times, normally 10.
8. The report distinguishes `MACRO_SUCCESS`, `RECOVERED_AND_RESUMED`, `FALLBACK_COMPLETED`, `FAILED`, `BLOCKED`, `UNKNOWN_OUTCOME`, and infrastructure errors.
9. The report includes device, workflow version, run IDs, step counts, LLM calls, failures, fixes, and remaining risks.

If a real device, model, credential, or app state is unavailable, stop at the blocked stage and report that limitation instead of fabricating a pass rate.

## 1. Establish context and safety

Use the repository-local runtime and an explicit device:

```bash
cd <mobilerun-repository>
adb devices
uv run mobilerun devices
uv run mobilerun --version
uv run mobilerun workflow --help
```

Before touching the phone, identify:

- target app/package and test account/environment;
- device serial; never rely on implicit device selection for a real run;
- whether the task has side effects; prefer simulator/test data;
- exact completion evidence, not just the last action;
- requested exploration count and final batch count.

Use the repository-local `uv run` entry point. Configuration resolves from an explicit `--config`, `MOBILERUN_CONFIG`, project `config.yaml`, then the user config. For Android state observation, prefer `device.use_tcp: true` and `device.portal_mode: required`. A Portal read failure should stop as an observation/infrastructure issue instead of silently falling back to UiAutomator and producing misleading trajectory evidence.

For trading, payment, messaging, deletion, account changes, or production data, require a simulator/test account and confirm the irreversible boundary. A simulated order is still a stateful side effect: verify it is cancelled/cleaned up after every run.

Never put API keys, passwords, tokens, or secret values into prompts, workflow JSON, screenshots, logs, or reports. Use `secret_id`/credential manager actions.

## 2. Explore with AI, bounded and evidence-first

Run the natural-language task with action recording. Start with 2–5 exploration attempts when the app is unfamiliar; do not loop indefinitely.

```bash
uv run mobilerun run "<task>" \
  --device <serial> \
  --save-trajectory action \
  --steps <bounded-step-limit>
```

For each attempt, record:

- trajectory path;
- final Agent result and reason;
- action count and action types;
- screenshots/UI state availability;
- model/provider used and model call count if available;
- exact failure step and visible device state;
- whether side effects were cleaned up.

Keep these trajectories, screenshots, state snapshots, and run records in the local ignored run directory. They are debugging evidence and may contain concrete workflow details, device identifiers, or private UI content.

Use a fresh app/device state between attempts when the task is stateful. Do not let a leftover order, modal, login, or selected tab make a later attempt appear successful.

If the task requires vision, enable it explicitly and record provider errors separately from app-flow errors. A `uiautomator`/Portal state failure is an infrastructure/state-observation failure, not an LLM reasoning failure.

Do not immediately promote the first successful natural-language trajectory. A model can report success while a postcondition is false.

## 3. Classify exploration failures before fixing

Classify each failed attempt into one primary category:

- `DEVICE`: offline, unauthorized, disconnected, emulator booting;
- `OBSERVATION`: Portal/UiAutomator XML failure, empty accessibility tree, stale state;
- `APP_ENTRY`: launch/splash/login/account selection;
- `NAVIGATION`: wrong tab, stale page, dynamic popup, ambiguous target;
- `DATA`: missing stock/account/test data or changed server response;
- `MODEL`: provider/API/tool protocol/vision failure;
- `WORKFLOW`: coordinate drift, missing pre-state, missing completion check;
- `SIDE_EFFECT`: order/message/payment/delete outcome not confirmed.

For each issue, write the cause and the smallest durable fix. Examples:

- add a stable selector instead of lowering every threshold;
- add a bounded wait only at a real transition;
- add a deterministic safe overlay handler;
- restart/re-enable Portal before blaming the model;
- add a postcondition for cancellation/zero fill;
- create a new workflow version instead of mutating the active artifact.

Never hide a failure by removing all `pre_state` guards. If an entry guard is inherently unstable because Launcher layout changes, make the app-entry action establish context and guard the first side-effecting action instead.

## 4. Select and consolidate a candidate

Inspect the trajectories and choose the candidate with the strongest evidence, not merely the shortest path:

```bash
uv run mobilerun macro list
uv run mobilerun macro replay trajectories/<candidate> \
  --device <serial> \
  --on-mismatch stop \
  --dry-run
```

Prefer a candidate with:

- action-level Macro v2 data;
- meaningful `pre_state` snapshots;
- stable resource IDs/content descriptions;
- explicit postconditions or a clear final UI assertion;
- no plaintext secrets;
- no unverified model-only success;
- no duplicate high-risk action after an unknown outcome.

If multiple exploration attempts reveal complementary fixes, create a new consolidated candidate/version. Keep the original trajectories as evidence.

## 5. Import, validate, and publish a draft

Import the candidate as a draft:

```bash
uv run mobilerun workflow import trajectories/<candidate> \
  --id <workflow-id> \
  --name "<human-readable name>" \
  [--parameter name] \
  [--parameter environment=staging]

uv run mobilerun workflow inspect <workflow-id>
uv run mobilerun workflow validate <workflow-id>
```

Add or review metadata before activation:

- `parameters` and literal `{{parameter}}` substitutions;
- `entry_check` for app/package/context;
- `completion_check` for the actual expected result;
- `policy.on_divergence`, starting with `stop`;
- bounded recovery count/action/time budgets;
- `allow_side_effect_retry: false` for high-risk actions;
- `auto_publish_repair: false`.

Validate every candidate change:

```bash
uv run mobilerun workflow validate <workflow-id> --version <N>
```

Activate only after validation:

```bash
uv run mobilerun workflow activate <workflow-id> --version <N>
```

The active pointer is the publish boundary. Preserve old versions for comparison and rollback.

## 6. Stabilize with deterministic baseline and recovery

First run the candidate with no recovery. This measures the workflow itself:

```bash
uv run mobilerun workflow run <workflow-id> \
  --version <N> \
  --device <serial> \
  --on-divergence stop
```

Only after the baseline is understood, test supervised recovery:

```bash
uv run mobilerun workflow run <workflow-id> \
  --version <N> \
  --device <serial> \
  --on-divergence recover
```

Recovery is successful only when:

1. a divergence is recorded;
2. the recovery agent or deterministic handler performs a bounded allowed action;
3. the failed-step precondition is re-observed and accepted by code;
4. the original workflow resumes at the correct step;
5. the final completion check passes.

A model response saying “done” is not recovery evidence. If the UI remains wrong, classify the run as `BLOCKED`/`FAILED` and preserve the journal.

Every workflow run keeps `manifest.json`, `result.json`, `journal.jsonl`, `artifacts/states/`, and `artifacts/screenshots/` under its run directory. Recovery events are recorded as `recovery_start`, `recovery_prompt`, `recovery_llm`, `recovery_action`, and `recovery_state`. When divergence occurs, `repair_proposal.json` captures the bounded recovery context and candidate actions with `auto_publish: false`. Use `uv run mobilerun workflow report <workflow-id> [--run-id <run-id>]` to review the timeline. Treat the proposal as input to a reviewed new version, never as an automatic workflow mutation.

## 7. Run the final batch, normally 10 times

Run sequentially on one device unless the user explicitly requests a device pool. Each run must have an isolated result/journal path and a clean test state.

For a deterministic stability batch:

```bash
for i in $(seq 1 10); do
  echo "===== RUN $i ====="
  uv run mobilerun workflow run <workflow-id> \
    --version <N> \
    --device <serial> \
    --on-divergence stop
 done
```

For an AI-supervised batch, replace `stop` with `recover`, but report both deterministic and recovered outcomes if both baselines were run.

Do not rerun silently after a failure. Record every requested run, including failures. If a high-risk action has `UNKNOWN_OUTCOME`, stop and inspect the device before the next run.

After the batch:

```bash
uv run mobilerun workflow runs <workflow-id>
```

Use the bundled aggregator for a concise report:

```bash
python <skill-path>/scripts/aggregate_runs.py \
  --workflow-root workflows/<workflow-id> \
  --limit 10 \
  --output <local-ignored-report-path>
```

The aggregator is for run-result evidence; it does not replace device cleanup or human review.

Keep the generated report and all run artifacts out of tracked documentation. Before committing source or generic example changes, stage them and run `python3 scripts/check_staged_privacy.py`. The gate rejects concrete workflows, runtime records, local absolute paths, credentials, and device-specific identifiers while allowing example/fixture paths.

## 8. Report format

Always produce a Markdown report with this structure:

```markdown
# <workflow> batch report
## Environment
- repository/runtime
- device serial and platform
- app/package and test environment
- workflow/version
## Exploration summary
- attempts and trajectory paths
- successes/failures
- failure categories and fixes
## Workflow changes
- selectors, waits, assertions, recovery policy
## Batch results
| run | status | steps | llm calls | recovery attempts | failure |
## Metrics
- requested runs
- completed runs
- effective pass rate
- strict deterministic pass rate
- recovered-and-resumed count
- blocked/failed/unknown count
- average duration if available
- total LLM calls
## Evidence
- active workflow path
- result/journal paths or run IDs
- final device cleanup/check
## Risks and next steps
```

Define pass rates explicitly:

- **Strict pass rate**: `MACRO_SUCCESS / requested runs`.
- **Supervised effective pass rate**: `(MACRO_SUCCESS + RECOVERED_AND_RESUMED) / requested runs`.
- `FALLBACK_COMPLETED` is not equivalent to recovered workflow completion unless the user explicitly allows fallback; report it separately.

If some runs were not executed because of infrastructure blockage, do not call the result a 10-run pass rate. Report `completed/requested` and the reason.

## 9. Completion checklist

Before responding, verify:

- [ ] all requested exploration attempts are accounted for;
- [ ] all failures have a category and a recorded fix or blocker;
- [ ] candidate workflow is validated and active;
- [ ] final batch count equals the request, or the shortfall is explicit;
- [ ] every run has a structured result;
- [ ] completion checks—not Agent prose—determine success;
- [ ] no secrets or unnecessary screenshots were committed;
- [ ] simulator/test-account side effects are cleaned up;
- [ ] report contains strict and supervised pass rates separately;
- [ ] remaining risks are visible.
