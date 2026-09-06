# TrustEval Studio

目标很简单：把一批散乱的线上问题，快速变成可执行评测集；接入算法团队的新模型批量验收；自动输出发布结论和优化洞察。

## 30 秒体验

无需 API Key，运行内置的脱敏 Demo：

```bash
git clone https://github.com/zjj1999/trust-eval-studio.git
cd trust-eval-studio
./demo.sh
```

脚本不需要安装依赖或配置 API Key，会直接运行完整 Pipeline，并打开 `runs/interview-demo/report.html`。

不想安装代码，也可以直接查看[在线产品 Demo](https://trust-eval-studio-v1.abuzz-horse-7302.chatgpt.site)。

## 面试官会看到什么

一次 Demo 会完整经过三步：

1. **评测集共创**：把原始 Question / Answer 转成结构化评测集；
2. **模型自动验收**：执行规则与语义评分，计算指标和发布 Gate；
3. **产品洞察**：输出失败聚类、责任层、代表 Case 和回归建议。

示例结果会生成在 `runs/interview-demo/`：

- `report.html`：可筛选的可视化报告；
- `algorithm-report.md`：给算法团队的优化报告；
- `results.json` / `results.csv`：逐题评分和整体指标；
- `review.csv`：PM / 专家审核评分标准的入口。

## 产品流程

### 1. 评测集共创 Agent

原始数据可以只有 `question` 和 `answer`：

```bash
trust-eval build --input batch.xlsx --workspace runs/batch-001
```

支持 CSV、Excel、JSON、JSONL、Markdown、TXT、DOCX。输出：

- `dataset-profile.json`：这批题在测什么、场景分布、标准缺口
- `cases.jsonl`：统一后的可执行评测集
- `review.csv`：Agent 起草、PM/专家确认的 ground truth 与评分标准

默认使用本地模板 Agent。需要真正的 LLM 共创时：

```bash
trust-eval build --input batch.xlsx --workspace runs/batch-001 \
  --architect openai --architect-model gpt-5.4-mini
```

也可以通过 `--architect command --architect-command "..."` 接公司内部 Agent。

PM 修改 `review.csv` 并将 `approved` 设为 `yes` 后：

```bash
trust-eval review --workspace runs/batch-001
```

没有批准的标准不能进入正式验收。

### 2. 模型自动验收 Runner

评已有 answer：

```bash
trust-eval evaluate --workspace runs/batch-001
```

调用算法团队的普通 HTTP Endpoint：

```bash
export MODEL_API_KEY="..."
trust-eval evaluate --workspace runs/batch-001 \
  --target http \
  --target-endpoint https://model.example.com/generate \
  --target-model doubao-test-v2 \
  --batch-id algorithm-iteration-042
```

请求协议：

```json
{
  "case_id": "case-001",
  "query": "用户问题",
  "conversation": [],
  "model": "doubao-test-v2"
}
```

Endpoint 返回：

```json
{
  "answer": "模型本轮回答",
  "tool_trace": [{"tool": "booking", "status": "success"}]
}
```

对于 OpenAI-compatible chat 接口，增加 `--target-protocol openai_chat`。本地或内部批处理脚本使用：

```bash
trust-eval evaluate --workspace runs/batch-001 \
  --target command --target-command "python call_internal_model.py"
```

评分 Judge 同样可以选择 deterministic、OpenAI 或内部 command：

```bash
trust-eval evaluate --workspace runs/batch-001 \
  --target http --target-endpoint https://model.example.com/generate \
  --judge openai --model gpt-5.4-mini
```

### 3. 产品洞察 Agent

一次 `evaluate` 会自动生成洞察。模型结果不变时，可以单独重新分析：

```bash
trust-eval report --workspace runs/batch-001
```

使用 LLM 洞察 Agent：

```bash
trust-eval report --workspace runs/batch-001 \
  --insight-agent openai --insight-model gpt-5.4-mini
```

最终输出：

- `model-outputs.jsonl`：模型批次的原始 answer、trace、延迟与错误
- `results.json` / `results.csv`：结构化逐题结果和整体指标
- `insights.json`：发布结论、优先问题、责任层和回归 Case
- `algorithm-report.md`：给算法团队的优化报告
- `report.html`：可归档、可筛选的独立页面

## 评分口径

每题只回答三个产品问题，各 0–2 分：

| 视角 | 问题 |
|---|---|
| 用户价值 | 用户的问题解决了吗？ |
| 产品可信 | 回答是否基于真实输入、证据和能力边界？ |
| 业务可上线 | 这个表现可以上线吗？ |

6 分为绿色；4–5 且没有 0 分为黄色；任一 0 分或总分不高于 3 为红色；证据不足为 `unknown`。红线优先于总分。

## 代码模块

```text
evalset_builder.py  评测集共创 Agent：理解数据集并补全 ground truth/rubric
model_runner.py      模型 Endpoint：批量生成待测 answer 和 trace
graders.py           评测 Judge：确定性规则、语义评分和发布 Gate
insights.py          产品洞察 Agent：失败聚类、责任层和回归建议
reporting.py         HTML、JSON、CSV、算法报告
cli.py               将三个产品模块组合为一条流水线
```

完整设计见 [三模块架构图](docs/architecture.md)。
