# TrustEval 产品架构：三个模块完成一次模型验收

```mermaid
flowchart LR
    subgraph M1["1. 评测集共创 Agent"]
        Raw["散乱业务数据<br/>线上 query / 测试 query<br/>Excel · 文档 · JSON"]
        Normalize["统一数据协议<br/>question · context · candidate answer"]
        Architect["理解评测目标<br/>补 Ground Truth · Rubric · 红线"]
        Review{"PM / 专家确认"}
        Evalset["可执行评测集<br/>cases.jsonl"]
        Raw --> Normalize --> Architect --> Review
        Review -->|批准| Evalset
        Review -->|修改| Architect
    end

    subgraph M2["2. 模型自动验收 Runner"]
        ModelEP["算法团队模型 Endpoint<br/>HTTP · OpenAI-compatible · Command"]
        Batch["批量请求模型<br/>生成本批 answer / trace"]
        Rules["确定性检查<br/>事实点 · 输入状态 · 工具结果 · 红线"]
        Judge["评测 Judge<br/>用户价值 · 产品可信 · 业务可上线"]
        Metric["指标与发布 Gate<br/>Green · Yellow · Red · Unknown"]
        ModelEP --> Batch
        Batch --> Rules
        Batch --> Judge
        Rules --> Metric
        Judge --> Metric
    end

    subgraph M3["3. 产品洞察 Agent"]
        Cluster["聚类失败原因<br/>问题码 · 场景 · 影响范围"]
        Decision["产品结论<br/>PASS · REVIEW · BLOCK"]
        Handoff["算法交付<br/>责任层 · 代表 Case · 优化动作"]
        View["可视化<br/>Dashboard · HTML · CSV · JSON"]
        Cluster --> Decision
        Cluster --> Handoff
        Decision --> View
        Handoff --> View
    end

    Evalset --> Batch
    Metric --> Cluster
    Handoff -. 修复后回归 .-> ModelEP
```

## 三个模块的产品定义

### 1. 评测集共创 Agent

输入可以只有 question 和已有 answer。模块先统一格式、理解整批 Case 想验证什么，再为每题起草 expected behavior、ground truth、检查点、三视角评分标准和上线红线。PM 不负责从零写标准，只确认 Agent 草稿和必须由专家核验的事实。

输出：`dataset-profile.json`、`cases.jsonl`、`review.csv`。

### 2. 模型自动验收 Runner

算法团队只提供一个待测模型 Endpoint。Runner 将评测集逐题发送给模型，保存 answer、延迟和工具 trace，再用确定性规则与语义 Judge 评分。规则负责可确定红线，Judge 负责语义质量；冲突时取保守结果。

输出：`model-outputs.jsonl`、逐题 U/P/B 分数、问题码、证据和发布 Gate。

### 3. 产品洞察 Agent

把逐题结果转成产品和算法可行动的结论：本批能否发布、最重要的失败簇是什么、应由模型/检索/工具/安全/评测数据哪一层负责、修复后需要回归哪些 Case。

输出：`insights.json`、`results.json/csv`、`algorithm-report.md`、`report.html` 和 Web 工作台。

## 核心人机分工

- Agent 做规模化工作：清洗、归一化、标准草拟、批量调用、评分、聚类和报告。
- PM 做高价值判断：评测目标、业务红线、上线门槛和争议 Case。
- 领域专家只处理必须核验的事实或高风险标准。
- 算法团队只需维护模型 Endpoint，并消费问题码、代表 Case 和回归清单。
