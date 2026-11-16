---
name: broker-daily-inspection
description: Operate the repository's broker daily inspection system. Use this skill whenever the user asks to add or update a broker profile, configure a broker password reference, run a daily brokerage inspection, verify login/KSGT routing/funds/order/cancel status, generate the compact broker summary, investigate an inspection failure, prepare the inspection for scheduled execution, or commit and push generic inspection code. It covers local broker profiles, safe read-only preflight, one-shot order and cancellation execution, evidence review, dated summary reports, anomaly lessons, privacy checks, and Git publication. Never expose secret values or commit concrete broker profiles, credentials, screenshots, journals, workflows, or run artifacts.
---

# Broker Daily Inspection Operator

Use the broker-neutral `broker-daily-inspection` workflow with a local broker profile. The profile supplies broker-specific display text, credential reference, order status text, and the current-order cancellation target. Keep the workflow logic shared so adding a broker does not duplicate the workflow.

Read these files before changing or running anything:

- `docs/workflow-runbook.md`
- `.agents/skills/mobilerun-workflow/SKILL.md`
- `config.yaml`
- `config/broker_profiles.yaml`
- `workflows/broker-daily-inspection/active.json`

Use the repository runtime from the repository root:

```bash
uv run mobilerun ...
```

Always pass an explicit device serial. Run `uv run mobilerun doctor` first and require ADB, Portal/TCP, accessibility, state, screenshot, and keyboard checks to be usable. If state observation falls back to UiAutomator when reliable Portal state is required, classify the run as an infrastructure/observation failure and stop.

## Safety boundary

A complete inspection submits one order and then cancels it. Treat the submission as a single side effect:

- Never run the full path without explicit confirmation immediately before execution.
- Use `--on-divergence stop` and keep side-effect retry disabled.
- Never retry after an unknown outcome. Inspect the account and order page first.
- Do not use a fallback Agent to continue after a blocked order or cancellation.
- Before a real run, confirm the target app, broker profile, device, stock code, quantity, and expected cleanup.
- If the user asks only for configuration, inspection, or a report, do not submit an order.

## Add or update a broker profile

Adding a broker normally requires a local credential reference and a small YAML profile. It does not require cloning the workflow.

1. Add the trade password to local `config/credentials.yaml` under a new secret ID. Enter the value locally and keep the file mode `600`; never paste or print the value.
2. Add a profile to local ignored `config/broker_profiles.yaml`:

```yaml
brokers:
  <profile_id>:
    broker_name: <visible broker name>
    password_secret_id: <credential id>
    stock_code: '<code>'
    quantity: '<quantity>'
    pending_statuses: '<status>|<status>'
    cancelled_statuses: '<status>|<status>'
    history_header_text: <history section text>
    cancel_target_text: <current order cancel text>
    active_cancel_texts: '<current order cancel text>'
```

3. Perform a read-only UI check before a complete run. Confirm that the target broker can be selected, the logged-in title matches, and the visible pending/cancelled status and current-order cancel text match the profile. If the app uses different page resources or navigation layers, stop and classify it as a UI adapter requirement instead of guessing coordinates.
4. Do not put real broker names, account identifiers, passwords, screenshots, or status dumps in tracked files, examples, prompts, commits, or chat summaries.

The profile is the only broker-specific input for the normal path. If the broker UI differs materially, create a reviewed adapter or workflow version and validate it before activation.

## Read-only preflight

Before a real inspection, run:

```bash
adb devices
uv run mobilerun doctor
uv run mobilerun workflow validate broker-daily-inspection --version <N>
uv run mobilerun workflow inspect broker-daily-inspection --version <N>
```

Use a read-only preflight to verify the profile and current session when possible. A preflight may select a broker and inspect the holdings page, but it must stop before the order form submission. Record its result locally; do not treat it as a complete inspection.

## Complete inspection

Use the profile entry point. It loads the profile, injects parameters, requires a side-effect acknowledgement, and writes the run evidence and per-run audit summary:

```bash
uv run mobilerun workflow broker-run \
  --workflow broker-daily-inspection \
  --broker <profile_id> \
  --version <active_version> \
  --device <serial> \
  --confirm-side-effect \
  --on-divergence stop
```

The workflow should perform these checks in order:

1. Accept an existing target-broker session or select and log in to the target broker.
2. Capture broker-session evidence.
3. Enter holdings and verify `available + market_value ~= total_assets` in code, before the order.
4. Open buy, inject stock code and quantity, and select the visible lower-limit/limit-down price.
5. Capture the filled order form and submit exactly once.
6. Open current orders and verify a profile-allowed pending status.
7. Select the unique profile-specified current-order cancel target, never a history control.
8. Confirm cancellation and verify a profile-allowed cancelled status.
9. Return to holdings and repeat the code-side funds check.

Read `result.json` and `journal.jsonl` for the decision. A successful run should contain `broker_session`, two `money_verification` events, a pending `order_status_verification`, a `cancel_target`, and a cancelled `order_status_verification`. The run directory also contains state snapshots, screenshots, the HTML timeline, and `audit-summary.html`.

After a successful draft validation, activate the validated version:

```bash
uv run mobilerun workflow activate broker-daily-inspection --version <N>
```

## Summaries

The per-run summary is written under the run directory. To combine several broker runs into the table used for daily review:

```bash
uv run mobilerun workflow audit-report \
  --workflow broker-daily-inspection \
  --run broker-daily-inspection:<run_id> \
  --run broker-daily-inspection:<run_id>
```

Without `--output`, the report is stored under:

```text
workflows/broker-daily-inspection/reports/YYYY-MM-DD.html
workflows/broker-daily-inspection/reports/YYYY-MM-DD.json
```

Repeated reports on the same date receive `_02`, `_03`, and later suffixes. Report these columns:

- broker
- connectivity
- KSGT route
- funds
- order
- cancel
- conclusion
- funds mismatch notes

Use `PASS` only when the required checks and cleanup passed. Use `WARN` for a recorded funds mismatch or an expected negative route result that still satisfies the profile. Use `FAILED` or `UNKNOWN_OUTCOME` for failed or uncertain side effects.

## Failures and lessons

On failure:

1. Stop before retrying any side-effecting action.
2. Read the final journal state, screenshots, result, and repair proposal locally.
3. Classify the failure as profile/config, UI divergence, device/Portal, provider, or unknown side-effect outcome.
4. Run `uv run mobilerun workflow scan --workflow broker-daily-inspection` when anomaly indexing is needed.
5. Use static repair planning first. Any proposed workflow repair remains a draft until reviewed, validated, replayed, and explicitly activated.
6. Keep lessons and scan state local; do not paste concrete run evidence into tracked docs.

## Commit and push

Only commit generic source, tests, docs, and skill changes. Before committing:

```bash
python3 scripts/check_staged_privacy.py
git diff --check
```

The privacy gate must reject concrete workflows, credentials, account data, device identifiers, screenshots, journals, trajectories, and local absolute paths. Never force-add ignored `workflows/`, `runs/`, `trajectories/`, or credential files. Push only after tests and the privacy gate pass. Report the commit hash and the local report path without exposing secrets or concrete UI evidence.

## Response format

For each operation, report:

```text
Plan: broker/profile, device, workflow version, side-effect boundary
Preflight: doctor, validation, Portal/state result
Execution: status, steps, LLM calls, recovery attempts
Inspection: connectivity, route, funds, order, cancel, conclusion
Evidence: run directory, timeline report, dated summary report
Next step: activation, scheduling, profile repair, or blocked reason
```
