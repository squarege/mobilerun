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
mobilerun workflow run order-search --device emulator-5554
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
