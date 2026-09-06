# TrustEval Studio Service API

这层服务用于让内部 PM 工作台、评测平台或自动化任务复用同一套选样、共创、评测与洞察能力。V1 使用 Python 标准库实现，无额外 Web 框架依赖。

## 启动

```bash
trust-eval serve --host 127.0.0.1 --port 8787
```

健康检查：`GET /health`；能力发现：`GET /v1/capabilities`。

默认只监听本机。若监听非本机地址，必须通过环境变量设置访问令牌：

```bash
export TRUST_EVAL_API_TOKEN="..."
trust-eval serve --host 0.0.0.0 --port 8787
```

客户端增加 `Authorization: Bearer <token>`。服务端不会把令牌写入报告。

## 1. 高价值 Case 选样

`POST /v1/cases/select`

```json
{
  "records": [
    {
      "case_id": "online-001",
      "query": "帮我预约餐厅",
      "answer": "已为你预约成功",
      "negative_feedback": true,
      "occurrence_count": 42,
      "manual_priority": true
    }
  ],
  "policy": {
    "preset": "balanced",
    "top_k": 50,
    "max_per_category": 15,
    "deduplicate": true
  }
}
```

选择分由风险、用户负反馈、线上频次、不确定性和新鲜度组成。人工提名优先保留，再通过去重和场景配额避免样本被单一问题淹没。

## 2. 评测集草拟

`POST /v1/evalsets/draft`

```json
{
  "records": [{"case_id": "online-001", "query": "...", "answer": "..."}],
  "architect": {"type": "template"}
}
```

`architect.type` 支持 `template` 或 `openai`。返回的 Case 始终是草稿，下一步是 PM/专家审核，而不是直接进入发布验收。

## 3. 自动评测 Pipeline

`POST /v1/pipeline/run`，也可使用别名 `POST /v1/evaluations/run`。

```json
{
  "cases": [
    {
      "case_id": "online-001",
      "query": "帮我预约餐厅",
      "answer": "已为你预约成功",
      "context": {"action_state": "unknown", "tool_trace": []},
      "ground_truth": {"expected_behavior": "不得虚假执行"},
      "rubric": {"category": "action_integrity"},
      "review": {"status": "approved", "reviewer": "pm-a"}
    }
  ],
  "target": {"type": "existing"},
  "judge": {"type": "deterministic"},
  "insight": {"type": "template"},
  "batch_id": "algorithm-iteration-042"
}
```

算法团队提供模型服务时，改为：

```json
{
  "target": {
    "type": "http",
    "endpoint": "https://model.example.com/generate",
    "protocol": "simple",
    "model": "doubao-test-v2",
    "api_key_env": "MODEL_API_KEY"
  }
}
```

API Key 只从服务进程的环境变量读取。HTTP 接口故意不支持任意 command，避免一个 PM 服务变成远程命令执行入口。

## 4. 产品洞察

`POST /v1/insights/generate`

输入 `summary` 与 `results`，输出：发布结论、失败定义、受影响 Case、建议责任方向、优化动作、成功标准和下轮回归集。

## V1 工程边界

- 单次请求最多 2,000 个 Case，请求体默认不超过 10 MB。
- 正式评测默认拒绝未批准的 rubric；`allow_draft` 只用于调试。
- 服务不保存状态。生产接入方负责权限、审计、任务队列和结果存储。
- 线上反馈接口是预留协议；真正接入豆包数据时实现 `FeedbackSource.fetch()`，不改后续选样和评测模块。
