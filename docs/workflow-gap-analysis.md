# MobileRun Workflow 基线与差距报告

审计提交：`e34004270a9d7b68824b94a3a5ba6698cefea69d`

## 已具备

- `mobilerun/macro/recorder.py`：动作级 Macro 记录和 `pre_state` 快照。
- `mobilerun/agent/trajectory/writer.py`：输出 Macro v2 `macro.json`。
- `mobilerun/macro/replay.py`：Android 动作回放、前置状态等待和状态匹配。
- `mobilerun/macro/matcher.py`：UI 节点和 package/activity 相似度匹配。
- `mobilerun/macro/cli.py`：`macro list` 和 `macro replay`。
- Secret 动作使用 `secret_id`，不把密码写入 Macro。

基线测试：Macro 相关原有测试通过；本次新增恢复/工作流测试后，定向回归共 32 项通过。

## 原有缺口

- `on-mismatch agent` 会调用普通 `run_command(goal)`，属于整任务 handoff，不会局部恢复后续跑。
- 单步动作失败后原实现仍可能继续执行后续动作。
- tap 主要使用录制坐标，没有稳定 selector 解析。
- 没有统一的结构化运行结果、步骤 journal、checkpoint 和 `UNKNOWN_OUTCOME`。
- Macro 元数据没有工作流状态、版本、参数和发布指针。

## 本次已补齐的基础能力

- `RecoveryOutcome`、`RunResult` 结构化执行契约。
- append-only JSONL `RunJournal`。
- `MacroPlayer.replay_macro_result()`：fail-fast、步骤状态、恢复预算、恢复后同一步续跑、post-state 校验。
- `ScopedRecoveryAgent`：仅允许 inspect/wait/back/唯一 selector tap/done，模型懒加载，仅异常路径调用。
- `WorkflowRegistry`：Macro 导入、draft、校验、版本目录、activate、运行报告和 runs 查询。
- `mobilerun workflow` CLI：import/list/inspect/validate/activate/run/runs。

## 尚未承诺

- 未在真实 Android 设备上执行本报告中的 E2E；需要连接可控模拟器或真机验证。
- 未实现设备池、定时调度服务、Web 管理界面和跨设备并发策略。
- selector 恢复当前依赖可访问性树；UI 树为空时会保守失败，不会盲点截图坐标。
- workflow 参数替换和测试断言仍需要按具体业务补充。
