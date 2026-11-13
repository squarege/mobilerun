# 工作流测试基座使用指南

## 1. 首次探索

```bash
mobilerun run "打开被测 App，搜索订单并验证结果" --save-trajectory action
mobilerun macro list
```

找到生成的轨迹目录后，先进行无模型回放检查：

```bash
mobilerun macro replay trajectories/<run> --on-mismatch stop
```

## 2. 导入、审核和发布

```bash
mobilerun workflow import trajectories/<run> \
  --id order-search \
  --name "订单搜索"

mobilerun workflow validate order-search
mobilerun workflow inspect order-search
mobilerun workflow activate order-search --version 1
```

导入后的版本默认是 `draft`。只有校验通过并显式激活后，才会被工作流运行命令执行。

## 3. 定时执行

```bash
mobilerun workflow run order-search --device <serial>
mobilerun workflow runs order-search
```

可以由 cron、CI 或外部调度系统调用 `workflow run`。当前命令本身不内置常驻调度器，避免把设备调度和测试平台强耦合。

## 4. 参数化

工作流元数据可以声明参数，例如：

```json
{
  "parameters": {
    "query": {"required": true},
    "environment": {"default": "staging"}
  }
}
```

Macro 动作中使用 `{{query}}`，运行时传入：

```bash
mobilerun workflow run order-search --param query=手机 --param environment=staging
```

参数替换是字面替换，不执行 Python、Shell 或其他表达式。

## 5. 异常恢复

```bash
mobilerun workflow run order-search --on-divergence recover
```

恢复 Agent 仅允许检查状态、等待、返回和点击唯一可访问性节点。恢复成功后必须重新匹配失败步骤的前置状态，代码确认通过后才会继续 Macro。验证码、支付确认、未知副作用或超过预算时会停止并返回结构化失败结果。

正常路径不调用 LLM；模型调用数记录在 `result.json` 中。

## 6. 执行日志和回顾

每次工作流运行都会在 `workflows/<id>/runs/<run-id>/` 下保存：

- `manifest.json`：工作流版本、设备、配置和运行时间
- `result.json`：最终状态、完成步骤、恢复次数和失败原因
- `journal.jsonl`：逐步状态、前后观测、匹配分数和恢复事件
- `artifacts/states/`：每一步的状态快照
- `artifacts/screenshots/`：每一步的前后截图
- `repair_proposal.json`：divergence 上下文、恢复模型交互、恢复动作和候选修复动作

生成可展开的 HTML 时间线：

```bash
mobilerun workflow report order-search
mobilerun workflow report order-search --run-id <run-id>
```

不传 `--run-id` 时使用最近一次运行。报告默认写入对应运行目录的 `report.html`，可以直接在浏览器中打开，查看每一步的动作、状态、匹配结果、恢复记录和截图。

恢复链路会记录 `recovery_start`、`recovery_prompt`、`recovery_llm`、`recovery_action` 和 `recovery_state` 事件。候选修复只写入 `repair_proposal.json`，默认 `auto_publish` 为 `false`；审核者需要确认前置状态、动作副作用和重复可行性后，再把候选动作导入新版本并重新验证。

## 7. 异常扫描与修复

扫描本地工作流运行证据，生成持久化的异常索引和人类可读摘要：

```bash
mobilerun workflow scan
mobilerun workflow scan --workflow order-search --version 3
```

扫描结果保存在本地忽略的 `runs/scans/` 目录中，包含 `index.jsonl`、`state.json`、每次扫描的 JSON/Markdown 摘要以及修复计划。异常有稳定 ID 和状态生命周期，可用于过滤和追溯。

先使用静态证据分诊；只有明确需要模型判断时才启用 AI：

```bash
mobilerun workflow repair <anomaly-id>
mobilerun workflow repair <anomaly-id> --ai [--with-screenshots]
```

修复计划只允许插入等待、返回、唯一 selector 点击，将坐标点击改为唯一 selector，或设置 package/selector completion check。不允许提高恢复预算、削弱前置状态、发明坐标或自动重试未知副作用。确认计划后，使用 `--create-draft` 生成下一个 draft 版本：

```bash
mobilerun workflow repair <anomaly-id> --create-draft
mobilerun workflow validate <workflow-id> --version <new-version>
mobilerun workflow activate <workflow-id> --version <new-version>
```

`--create-draft` 不会自动激活。只有显式激活并在测试设备上重新验证通过后，才把异常标记为已修复。
