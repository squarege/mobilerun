---
name: mobilerun-workflow-runner
description: Run an existing Mobilerun workflow interactively. When invoked directly, first list available workflows, let the user choose one, collect device/version/mode/repetition requirements, execute with or without AI recovery, batch-run when requested, and produce an auditable summary report.
---

# Mobilerun Workflow Runner

This is an operator skill, not a workflow authoring skill. It runs an already-created workflow and explains the result. The user controls the workflow, device, AI-recovery mode, repetition count, and stopping policy.

## Invocation contract

When this skill is invoked directly:

1. Find the Mobilerun repository root.
2. Run `uv run mobilerun workflow list`.
3. Show the available workflow IDs, names, status, and active versions.
4. If the user already specified a workflow, show the list briefly and select that workflow. Otherwise ask the user to choose an ID before running anything.
5. Collect or infer:
   - workflow ID and optional version;
   - explicit device serial;
   - divergence mode: `stop` for no AI correction, or `recover` for bounded AI/local recovery;
   - run count, default `1`;
   - whether to stop the batch after the first failure or continue all requested runs;
   - report path. Use a local ignored run-artifact path by default. Do not default to a tracked `docs/` path because workflow details, device identifiers, and screenshots are private.

Do not silently choose a workflow or device when multiple choices exist. Do not start a real-device run until the selected workflow, device, mode, and count are clear.

## Safety and preflight

Before execution:

```bash
adb devices
uv run mobilerun devices
uv run mobilerun workflow inspect <workflow-id> [--version <N>]
uv run mobilerun workflow validate <workflow-id> [--version <N>]
```

Resolve configuration before the device run. Use the repository-local `uv run` entry point, run from the project root or set `MOBILERUN_CONFIG`, and prefer `device.use_tcp: true` with `device.portal_mode: required` for Android state observation. If Portal is unavailable, stop as an observation/infrastructure failure instead of allowing an implicit UiAutomator fallback to influence the run.

Require the selected version to be validated. Prefer an active version for normal use. If the workflow has trading, payment, messaging, deletion, account, or other side effects, confirm that the device uses a simulator/test account and that its completion check cleans up the side effect.

Use an explicit device on every run:

```bash
--device <serial>
```

Never expose credentials, tokens, or secret values in the report. Do not commit screenshots or raw UI dumps unless the user explicitly requests them.

## Execution modes

### No-AI correction

Use this to measure deterministic workflow stability:

```bash
uv run mobilerun workflow run <workflow-id> \
  --version <N> \
  --device <serial> \
  --on-divergence stop
```

Interpretation: any divergence stops the run. This mode should normally produce `llm_calls: 0`.

### AI/local recovery allowed

Use this when the user explicitly requests AI correction, recovery, or supervision:

```bash
uv run mobilerun workflow run <workflow-id> \
  --version <N> \
  --device <serial> \
  --on-divergence recover
```

Recovery is only successful when the runner's code-side state check passes and the original workflow resumes. A model message claiming success is not evidence. Report recovery attempts, LLM calls, recovered steps, and any blocked result.

Use the run's `journal.jsonl` and `repair_proposal.json` to reconstruct recovery. The journal records `recovery_start`, `recovery_prompt`, `recovery_llm`, `recovery_action`, and `recovery_state`, including the divergence context, attempted bounded actions, and state re-check. Proposals have `auto_publish: false` and require review before importing a new workflow version.

### Single run

For one run, execute the selected command directly and preserve its JSON result. Report:

- status;
- completed/total steps;
- LLM calls;
- recovery attempts;
- failure reason;
- result/journal/repair-proposal paths;
- HTML timeline path from `uv run mobilerun workflow report <workflow-id> [--run-id <run-id>]`;
- final completion check.

The run directory also contains `manifest.json`, `artifacts/states/`, and `artifacts/screenshots/`. Keep this evidence local and out of Git. Before committing any source or generic example changes, stage them and run `python3 scripts/check_staged_privacy.py` so concrete workflows, runtime records, local paths, credentials, and device identifiers are rejected.

### Multiple runs

For `N > 1`, run exactly N sequentially unless the user asks for controlled parallelism. Do not silently retry a failed run; each requested run gets one result. Use isolated CLI invocations so each run receives its own journal:

```bash
for i in $(seq 1 <N>); do
  echo "===== RUN $i / <N> ====="
  uv run mobilerun workflow run <workflow-id> \
    --version <N-version> \
    --device <serial> \
    --on-divergence <stop|recover>
done
```

If the user says “run 10 times,” execute 10 attempts, including failures. If the user says “stop on failure,” stop immediately and report `completed/requested`; otherwise continue and report every attempt.

After a batch:

```bash
uv run mobilerun workflow runs <workflow-id>
```

Prefer the latest N run records that belong to this invocation. Do not mix old historical runs into the requested batch. If run IDs cannot be unambiguously separated, say so and use a fresh output directory or ask the user to clean/select the range.

## Status and pass-rate semantics

Use these meanings:

- `MACRO_SUCCESS`: deterministic workflow completed and completion check passed.
- `RECOVERED_AND_RESUMED`: divergence occurred, bounded recovery passed code-side validation, and the original workflow completed.
- `FALLBACK_COMPLETED`: a fallback Agent completed something; do not count it as workflow recovery unless the user explicitly allows it.
- `FAILED`: workflow action or completion check failed.
- `BLOCKED`: recovery or policy stopped execution.
- `UNKNOWN_OUTCOME`: a side-effect result is uncertain; never count as a pass.
- `INFRASTRUCTURE_ERROR`: device, Portal, UiAutomator, provider, or host failure.

For a batch, report both:

```text
strict pass rate = MACRO_SUCCESS / requested runs
supervised effective pass rate = (MACRO_SUCCESS + RECOVERED_AND_RESUMED) / requested runs
```

Also report `completed/requested` when the batch was interrupted. Do not call an incomplete batch a 10-run pass rate.

## Report output

Write a Markdown report to the user-requested local ignored path. Keep concrete workflow details, device identifiers, screenshots, and run evidence out of tracked documentation:

```markdown
# <workflow> run report
## Request
- workflow/version
- device
- mode: stop or recover
- requested runs
- stop-on-failure policy
## Preflight
- validation result
- active version
- device state
- completion check
## Results
| run | status | steps | llm calls | recovery attempts | failure |
## Metrics
- completed/requested
- strict pass rate
- supervised effective pass rate
- failed/blocked/unknown/infrastructure counts
- total LLM calls
## Evidence
- run IDs
- result.json paths
- journal paths
- repair proposals
## Problems and actions
- observed issue
- classification
- action taken
## Final assessment
- usable/not usable for scheduled execution
- remaining risks
- recommended next step
```

Keep the report factual. Separate observations from inferences. If a run failed before the model was called, classify it as an observation/device/infrastructure problem rather than a model reasoning failure.

## Completion checklist

Before responding:

- [ ] workflow list was shown;
- [ ] user selection and device were explicit;
- [ ] requested mode and run count were honored;
- [ ] workflow was validated before execution;
- [ ] every requested attempt is represented;
- [ ] no unknown side effect was silently retried;
- [ ] pass-rate denominator is the requested count;
- [ ] strict and supervised rates are separate;
- [ ] report path is provided;
- [ ] remaining risks and next steps are stated.
