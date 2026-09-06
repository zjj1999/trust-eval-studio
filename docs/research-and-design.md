# 多轮对话可信度评测：调研与 V1 设计

## 结论

V1 采用“轻平台、重口径”：多格式输入统一为 JSONL；Agent 起草 rubric，PM/领域专家只审核标准和争议样本；确定性规则锁定红线，可选 LLM Judge 评价语义；最终把三项 0–2 分转成清楚的发布结论，并同时生成 PM 看板和算法报告。

从产品使用路径看，所有工程能力被收拢为四个模块：业务数据回流与选样负责从线上反馈中形成透明候选池；评测集共创 Agent 负责把散乱 question/answer 变成经过确认的评测集；模型自动验收 Runner 负责调用算法团队提供的 Endpoint 并完成批量评分；产品洞察 Agent 负责把逐题结果变成发布决策、失败定义、优化动作和回归清单。PM 的核心动作只有“确认选样目标、审核标准和消费洞察”，不需要介入批量执行过程。

这套流程回答三个简单问题：

1. 用户视角：问题解决了吗？
2. 产品视角：回答是否基于真实输入、证据和能力边界？
3. 业务视角：这个表现可以上线吗？

每项 0 分代表不可接受，1 分代表部分满足或需要复核，2 分代表充分满足。总分 6 为绿色；4–5 且没有 0 分为黄色；任一 0 分或总分不高于 3 为红色；关键信息不足为 unknown。红线单独计数，不能被其他维度高分平均掉。

## 调研如何影响设计

Anthropic 建议 Agent eval 关注实际结果和环境状态，而不只是模型声称成功，并强调让最了解用户需求的产品经理、领域专家参与定义成功；方法上组合确定性评分、LLM Judge 和人工评估。因此 V1 将附件状态、工具 trace 与最终 action state 放进标准数据协议，并把 PM 审核设为正式运行前的门槛。[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

OpenAI 的评测接口把 model grader、label/string check、Python grader 和 multi-grader 视为可组合部件，Evals API 也采用结构化数据 schema 与逐项输出。V1 采用同样的可组合思想，但用本地 JSONL、规则插件和可选 Judge 保持轻量。[Graders API](https://platform.openai.com/docs/api-reference/graders?api-mode=chat)；[Evals API](https://platform.openai.com/docs/api-reference/evals/deleteRun?lang=python)

OpenAI 对 hallucination 的研究指出，强迫模型猜测会放大错误，应允许表达不确定性。因此 factual case 缺少 reference 时返回 `unknown`，而不是根据流畅度猜一个分；自信错误、虚假输入访问和虚假执行受到更重惩罚。[Why language models hallucinate](https://openai.com/index/why-language-models-hallucinate/)

来自真实用户反馈的严重失败适合成为针对性 eval，但不能被解释成生产分布发生率。因此 16 道题适合用来验证能力边界和红线，却不能直接给出“线上 56% 通过”之类的总体结论。[GPT-5.5 Instant System Card](https://deploymentsafety.openai.com/gpt-5-5-instant/dynamic-mental-health-benchmarks-with-adversarial-user-simulations)

MLflow 的 GenAI 评测将 inputs、expectations、human feedback 和 traces 结合，并强调让 Judge 与人工判断对齐。Promptfoo 则证明 CLI 工作流可以自然输出 JSON、CSV、JSONL 与 HTML，并组合确定性/模型辅助断言。V1 借鉴两者的可追溯性与便携输出，但不引入重型运行依赖。[MLflow evaluation](https://mlflow.org/docs/latest/genai/eval-monitor/)；[LLM judge workflow](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/workflow/)；[Promptfoo outputs](https://www.promptfoo.dev/docs/configuration/outputs/)；[Promptfoo assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/)

## 产品与算法 co-design

产品经理不需要逐题写复杂打分提示，而要负责五件事：选择本轮业务目标、确认代表场景、写清期望行为、标红不可上线行为、确定阈值。Agent 负责把线上候选案例按价值排序并变成上述结构，同时标出需要事实专家介入的缺口。算法团队收到的不是一个模糊总分，而是失败定义、问题码、证据、建议责任方向、优化动作、成功标准和可直接回归的案例 ID。

业务回流不能只拿“最差的 Case”，否则无法说明主要体验；也不能只按频次抽样，否则会遗漏低频高风险。因此 V1 使用透明的多因素价值分，并保留三个可解释策略：人工提名优先、相似 Query 去重、场景配额保证多样性。选样报告只说明“为什么这些 Case 值得进入本轮评测”，不把定向样本当成线上总体分布。

生产化前应额外建立 50–100 条双人标注的校准集，比较 Judge 与人工在三个维度上的一致率，并重点报告红线召回。修复验证需要区分 capability run 与 regression run；同一回归 run 固定模型设置、rubric 版本和数据指纹，才能判断模型是否真的改善。

## V1 边界

当前离线 deterministic Judge 用于演示端到端自动化，不替代语义 Judge。OpenAI adapter 和通用 command adapter 已提供，但需要调用方配置密钥或内部命令。真实工具类案例若没有 trace/最终状态，只能进入 unknown 或被红线规则保守处理。V1 HTTP Service 无状态且默认仅监听本机，生产接入仍需由内部平台补齐账号权限、队列、审计和长期存储。HTML 报告是单文件，可归档和发送；Web 工作台展示同一份生成结果。
