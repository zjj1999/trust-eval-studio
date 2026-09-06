from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .insights import ISSUE_PLAYBOOK


def write_results_csv(path: str | Path, results: list[dict[str, Any]]) -> None:
    fields = [
        "case_id",
        "category",
        "status",
        "total_score",
        "user_value",
        "product_trust",
        "business_acceptability",
        "redline",
        "needs_review",
        "issue_codes",
        "judge",
        "query",
        "answer",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    "case_id": item["case_id"],
                    "category": item["category"],
                    "status": item["status"],
                    "total_score": item["total_score"],
                    "user_value": item["scores"]["user_value"],
                    "product_trust": item["scores"]["product_trust"],
                    "business_acceptability": item["scores"]["business_acceptability"],
                    "redline": item["redline"],
                    "needs_review": item["needs_review"],
                    "issue_codes": ";".join(item["issue_codes"]),
                    "judge": item["judge"],
                    "query": item["query"],
                    "answer": item["answer"],
                }
            )


def _issue_clusters(results: list[dict[str, Any]]) -> list[tuple[str, int, list[str]]]:
    cases_by_issue: dict[str, list[str]] = defaultdict(list)
    for item in results:
        for code in item["issue_codes"]:
            cases_by_issue[code].append(item["case_id"])
    return sorted(((code, len(case_ids), case_ids) for code, case_ids in cases_by_issue.items()), key=lambda row: (-row[1], row[0]))


def algorithm_report(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    run_meta: dict[str, Any],
    insights: dict[str, Any] | None = None,
) -> str:
    category_counts = Counter(item["category_name"] for item in results)
    failing_by_category = Counter(item["category_name"] for item in results if item["status"] in {"red", "unknown"})
    lines = [
        "# TrustEval 算法优化报告",
        "",
        f"- 运行时间：{run_meta['generated_at']}",
        f"- Judge：{run_meta['judge']}",
        f"- 数据指纹：`{run_meta['dataset_sha256']}`",
        f"- 发布结论：**{summary['release_decision'].upper()}** — {summary['release_reason']}",
        "",
        "## 一页结论",
        "",
        f"共 {summary['total']} 题：绿色 {summary['counts']['green']}、黄色 {summary['counts']['yellow']}、红色 {summary['counts']['red']}、证据不足 {summary['counts']['unknown']}。",
        f"红线 {summary['redlines']} 题，人工复核队列 {summary['review_queue']} 题；审核覆盖率 {summary['review_coverage']:.0%}。",
        "",
        "三个维度平均分（每项满分 2）："
        f"用户价值 {summary['dimension_averages']['user_value']}，"
        f"产品可信 {summary['dimension_averages']['product_trust']}，"
        f"业务可上线 {summary['dimension_averages']['business_acceptability']}。",
        "",
        "## 产品洞察 Agent",
        "",
        (insights or {}).get("executive_summary", "暂无额外洞察。"),
        "",
        "## 失败簇与建议责任层",
        "",
        "| 问题码 | 数量 | 代表案例 | 建议责任层 | 下一步 |",
        "|---|---:|---|---|---|",
    ]
    clusters = _issue_clusters(results)
    if not clusters:
        lines.append("| 无 | 0 | - | - | 保留当前结果作为回归基线 |")
    for code, count, case_ids in clusters:
        definition = ISSUE_PLAYBOOK.get(code, {})
        owner = definition.get("owner", "待 triage")
        recommendation = definition.get("action", "结合证据复核后分配责任层。")
        lines.append(f"| `{code}` | {count} | {', '.join(case_ids[:4])} | {owner} | {recommendation} |")
    priorities = (insights or {}).get("top_priorities", [])
    lines.extend(["", "## 优化任务卡", ""])
    if not priorities:
        lines.append("当前没有失败任务；保留本批结果作为后续回归基线。")
    for index, priority in enumerate(priorities[:5], start=1):
        lines.extend(
            [
                f"### P{index} · {priority.get('title', priority.get('issue_code', '待定义问题'))}",
                "",
                f"- **失败定义**：{priority.get('definition', '结合逐题证据补充定义')}",
                f"- **影响 Case**：{', '.join(priority.get('case_ids', [])) or '-'}",
                f"- **负责方向**：{priority.get('owner', '待产品与算法共同判断')}",
                f"- **优化动作**：{priority.get('action', '结合证据完成归因')}",
                f"- **完成标准**：{priority.get('success_criteria', '在固定回归集上验证问题已消失')}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## 场景分布",
            "",
            "| 场景 | 样本数 | 红色/未决 |",
            "|---|---:|---:|",
        ]
    )
    for category, count in category_counts.most_common():
        lines.append(f"| {category} | {count} | {failing_by_category[category]} |")
    lines.extend(
        [
            "",
            "## 逐题证据",
            "",
            "| 案例 | 状态 | U/P/B | 问题码 | 证据摘要 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in results:
        scores = item["scores"]
        score_text = f"{scores['user_value']}/{scores['product_trust']}/{scores['business_acceptability']}"
        evidence = "；".join(item["evidence"][:2]).replace("|", "\\|")
        lines.append(
            f"| {item['case_id']} | {item['status']} | {score_text} | "
            f"{', '.join(item['issue_codes']) or '-'} | {evidence} |"
        )
    lines.extend(
        [
            "",
            "## 给算法团队的使用方式",
            "",
            "1. 优先处理红线，再处理高频失败簇，不按总分平均稀释风险。",
            "2. 用代表案例复现并标注责任层：数据、提示词、模型、工具编排或安全策略。",
            "3. 修复后在相同数据指纹和 Judge 版本上重跑；已修复案例进入 regression run。",
            "4. `unknown` 不是模型通过，应补齐 reference、附件状态或 trace 后重评。",
            "",
            "## 口径限制",
            "",
            "本报告展示的是定向评测集结果，不代表线上真实发生率。离线 deterministic Judge 只能确认显式规则；语义质量上线前需经人工校准的 LLM Judge 或抽样复核。",
            "",
        ]
    )
    return "\n".join(lines)


def html_report(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    run_meta: dict[str, Any],
    insights: dict[str, Any] | None = None,
) -> str:
    payload = json.dumps(
        {"summary": summary, "results": results, "run": run_meta, "insights": insights or {}},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>TrustEval Studio 评测报告</title>
  <style>
    :root{{--ink:#102c2b;--muted:#61706e;--line:#d8e1de;--paper:#f7f7f2;--card:#fff;--teal:#0f766e;--red:#c2413a;--yellow:#b7791f;--green:#23815c;--unknown:#65727a}}
    *{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 85% 0,#dceee8 0,transparent 30%),var(--paper);color:var(--ink);font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif}}
    .wrap{{max-width:1180px;margin:auto;padding:38px 24px 64px}} header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:28px}} h1{{font-size:34px;line-height:1.1;margin:4px 0 10px;letter-spacing:-.03em}} .eyebrow{{color:var(--teal);font-weight:700;letter-spacing:.11em;text-transform:uppercase}} .muted{{color:var(--muted)}} .decision{{padding:11px 16px;border:1px solid var(--line);border-radius:999px;background:#fff;font-weight:800}} .decision.block{{color:var(--red);border-color:#edb9b5;background:#fff4f2}} .decision.pass{{color:var(--green)}}
    .metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:22px 0}} .metric,.panel,.priority{{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 30px rgba(22,54,50,.05)}} .metric{{padding:16px}} .metric strong{{display:block;font-size:27px;margin-top:3px}} .panel{{padding:18px;margin-top:14px}} .priority-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}} .priority{{padding:18px}} .priority h3{{margin:8px 0;font-size:17px}} .priority p{{margin:7px 0}} .priority .cases{{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;color:var(--teal)}} .filters{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}} button{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 12px;cursor:pointer;color:var(--ink)}} button.active{{background:var(--ink);color:#fff;border-color:var(--ink)}} select{{border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:#fff;color:var(--ink)}}
    table{{width:100%;border-collapse:collapse;margin-top:12px}} th,td{{text-align:left;border-top:1px solid var(--line);padding:12px 10px;vertical-align:top}} th{{color:var(--muted);font-size:12px}} tr{{cursor:pointer}} tr:hover{{background:#f2f7f5}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}} .green{{background:var(--green)}} .yellow{{background:var(--yellow)}} .red{{background:var(--red)}} .unknown{{background:var(--unknown)}} code{{font:12px ui-monospace,SFMono-Regular,monospace;background:#eef3f1;border-radius:6px;padding:2px 5px}}
    dialog{{width:min(760px,calc(100% - 32px));border:1px solid var(--line);border-radius:18px;padding:0;box-shadow:0 28px 80px rgba(13,42,39,.2)}} dialog::backdrop{{background:rgba(10,32,30,.35)}} .dialog-body{{padding:24px}} .close{{float:right}} .score-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:18px 0}} .score{{border:1px solid var(--line);border-radius:12px;padding:12px}} .score b{{font-size:22px;display:block}} .copy{{white-space:pre-wrap;background:#f5f7f5;padding:12px;border-radius:10px}} ul{{padding-left:20px}} footer{{margin-top:24px;color:var(--muted);font-size:12px}}
    @media(max-width:760px){{.metrics,.priority-grid{{grid-template-columns:repeat(1,1fr)}} header{{display:block}} .decision{{display:inline-block;margin-top:14px}} .hide-mobile{{display:none}}}}
  </style>
</head>
<body><div class="wrap">
  <header><div><div class="eyebrow">TrustEval Studio · Run report</div><h1>先判断能不能上线，再解释为什么失败</h1><div class="muted" id="run-meta"></div></div><div id="decision" class="decision"></div></header>
  <section class="metrics" id="metrics"></section>
  <section class="panel"><div class="eyebrow">产品洞察 Agent</div><strong id="insight-summary"></strong></section>
  <section class="priority-grid" id="priorities"></section>
  <section class="panel"><div class="filters"><strong>筛选</strong><button data-status="all" class="active">全部</button><button data-status="green">绿色</button><button data-status="yellow">黄色</button><button data-status="red">红色</button><button data-status="unknown">待复核</button><select id="category"><option value="all">全部场景</option></select></div>
    <table><thead><tr><th>案例</th><th>结果</th><th>场景</th><th>U / P / B</th><th class="hide-mobile">问题码</th><th class="hide-mobile">复核</th></tr></thead><tbody id="rows"></tbody></table>
  </section>
  <footer>口径：U=用户价值、P=产品可信、B=业务可上线；任一红线不会被平均分抵消。定向评测结果不等同于线上发生率。</footer>
</div>
<dialog id="detail"><div class="dialog-body"><button class="close" onclick="detail.close()">关闭</button><div id="detail-content"></div></div></dialog>
<script>
const DATA={payload}; let statusFilter='all'; let categoryFilter='all';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const s=DATA.summary,r=DATA.results;
document.querySelector('#run-meta').textContent=`${{DATA.run.generated_at}} · ${{DATA.run.judge}} · ${{s.total}} 个案例`;
document.querySelector('#insight-summary').textContent=DATA.insights.executive_summary||'暂无额外洞察';
document.querySelector('#priorities').innerHTML=(DATA.insights.top_priorities||[]).slice(0,4).map((x,i)=>`<article class="priority"><div class="eyebrow">P${{i+1}} · ${{esc(x.issue_code)}}</div><h3>${{esc(x.title||x.issue_code)}}</h3><p class="muted">${{esc(x.definition||'')}}</p><p><strong>怎么改：</strong>${{esc(x.action||'')}}</p><p><strong>怎样算修好：</strong>${{esc(x.success_criteria||'')}}</p><p class="cases">${{(x.case_ids||[]).map(esc).join(' · ')}}</p></article>`).join('');
const decision=document.querySelector('#decision'); decision.textContent=`${{s.release_decision.toUpperCase()}} · ${{s.release_reason}}`; decision.classList.add(s.release_decision);
document.querySelector('#metrics').innerHTML=[['绿色通过',s.counts.green],['发布红线',s.redlines],['待复核',s.review_queue],['用户价值',s.dimension_averages.user_value??'—'],['产品可信',s.dimension_averages.product_trust??'—']].map(x=>`<div class="metric"><span class="muted">${{x[0]}}</span><strong>${{x[1]}}</strong></div>`).join('');
const categories=[...new Set(r.map(x=>x.category_name))]; document.querySelector('#category').innerHTML+=[...categories].map(x=>`<option>${{esc(x)}}</option>`).join('');
function render(){{const visible=r.filter(x=>(statusFilter==='all'||x.status===statusFilter)&&(categoryFilter==='all'||x.category_name===categoryFilter));document.querySelector('#rows').innerHTML=visible.map(x=>`<tr data-id="${{esc(x.case_id)}}"><td><strong>${{esc(x.case_id)}}</strong></td><td><span class="dot ${{x.status}}"></span>${{x.status}}</td><td>${{esc(x.category_name)}}</td><td>${{x.scores.user_value??'—'}} / ${{x.scores.product_trust??'—'}} / ${{x.scores.business_acceptability??'—'}}</td><td class="hide-mobile">${{x.issue_codes.map(c=>`<code>${{esc(c)}}</code>`).join(' ')||'—'}}</td><td class="hide-mobile">${{x.needs_review?'需要':'—'}}</td></tr>`).join('')||'<tr><td colspan="6">没有匹配结果</td></tr>';document.querySelectorAll('tbody tr[data-id]').forEach(el=>el.onclick=()=>show(el.dataset.id));}}
function show(id){{const x=r.find(i=>i.case_id===id);const dims=[['用户价值','user_value'],['产品可信','product_trust'],['业务可上线','business_acceptability']];document.querySelector('#detail-content').innerHTML=`<div class="eyebrow">${{esc(x.category_name)}} · ${{esc(x.status)}}</div><h2>${{esc(x.case_id)}}</h2><div class="score-grid">${{dims.map(d=>`<div class="score"><span class="muted">${{d[0]}}</span><b>${{x.scores[d[1]]??'—'}} / 2</b><small>${{esc(x.rationales[d[1]])}}</small></div>`).join('')}}</div><h3>问题</h3><div class="copy">${{esc(x.query)}}</div><h3>回答</h3><div class="copy">${{esc(x.answer)}}</div><h3>证据</h3><ul>${{x.evidence.map(e=>`<li>${{esc(e)}}</li>`).join('')}}</ul><h3>问题码</h3><p>${{x.issue_codes.map(c=>`<code>${{esc(c)}}</code>`).join(' ')||'无'}}</p>`;detail.showModal();}}
document.querySelectorAll('[data-status]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-status]').forEach(x=>x.classList.remove('active'));b.classList.add('active');statusFilter=b.dataset.status;render();}});document.querySelector('#category').onchange=e=>{{categoryFilter=e.target.value;render();}};render();
</script></body></html>"""


def write_reports(
    workspace: str | Path,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    run_meta: dict[str, Any],
    insights: dict[str, Any] | None = None,
) -> None:
    target = Path(workspace)
    write_results_csv(target / "results.csv", results)
    (target / "algorithm-report.md").write_text(
        algorithm_report(summary, results, run_meta, insights), encoding="utf-8"
    )
    (target / "report.html").write_text(html_report(summary, results, run_meta, insights), encoding="utf-8")
