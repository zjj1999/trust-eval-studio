import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Database,
  FileCheck2,
  PlugZap,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import profile from '@/examples/workspace/dataset-profile.json';
import report from '@/examples/workspace/results.json';

const statusStyle = {
  green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  yellow: 'border-amber-200 bg-amber-50 text-amber-700',
  red: 'border-rose-200 bg-rose-50 text-rose-700',
  unknown: 'border-slate-200 bg-slate-50 text-slate-700',
};

export default function Home() {
  const { summary, results, insights } = report;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/80 bg-card/90">
        <div className="mx-auto flex max-w-[1480px] items-center justify-between px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Sparkles className="size-5" />
            </span>
            <div>
              <p className="font-heading text-lg font-semibold tracking-tight">TrustEval Studio</p>
              <p className="text-xs text-muted-foreground">模型产品团队的自动化评测流水线</p>
            </div>
          </div>
          <Badge className="bg-rose-600 text-white">
            <ShieldAlert data-icon="inline-start" /> 本批次 · BLOCK
          </Badge>
        </div>
      </header>

      <div className="mx-auto max-w-[1480px] px-5 py-8 lg:px-8">
        <section className="mb-7 grid gap-5 lg:grid-cols-[1.5fr_1fr] lg:items-end">
          <div>
            <p className="mb-2 text-sm font-semibold text-primary">从一批 Query 到一次发布决策</p>
            <h1 className="max-w-4xl font-heading text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
              PM 确认标准，Agent 完成建集、验收和洞察
            </h1>
            <p className="mt-3 max-w-3xl leading-7 text-muted-foreground">
              不要求业务数据一开始就完美。先把散乱 question/answer 变成可执行评测集，再接入算法模型 Endpoint，最后直接拿到可行动的优化结论。
            </p>
          </div>
          <Card className="border-0 bg-primary text-primary-foreground shadow-lg shadow-primary/10 ring-0">
            <CardHeader>
              <CardDescription className="text-primary-foreground/65">产品洞察 Agent</CardDescription>
              <CardTitle className="text-xl leading-7">{insights.executive_summary}</CardTitle>
            </CardHeader>
          </Card>
        </section>

        <section className="mb-7 grid gap-3 xl:grid-cols-[1fr_auto_1fr_auto_1fr] xl:items-stretch">
          <ProductStage
            step="01"
            icon={<Database />}
            title="评测集共创 Agent"
            description="理解这批题要测什么，补全 Ground Truth、评分标准和红线。"
            inputs="Excel / 文档 / 线上 Query"
            output={`${profile.case_count} 条可审核 Case · ${profile.domain_review_count} 条需专家确认`}
          />
          <ArrowRight className="m-auto hidden size-5 text-muted-foreground xl:block" />
          <ProductStage
            step="02"
            icon={<PlugZap />}
            title="模型自动验收 Runner"
            description="连接算法团队的模型 Endpoint，批量生成回答并自动评分。"
            inputs="HTTP / OpenAI-compatible / Command"
            output={`${summary.total} 条已评 · ${summary.redlines} 个发布红线`}
          />
          <ArrowRight className="m-auto hidden size-5 text-muted-foreground xl:block" />
          <ProductStage
            step="03"
            icon={<BarChart3 />}
            title="产品洞察 Agent"
            description="聚类失败原因，给出发布决策、责任层和下一轮回归清单。"
            inputs="逐题得分 / 证据 / 问题码"
            output={`${insights.top_priorities.length} 个优化方向 · ${summary.review_queue} 条待复核`}
          />
        </section>

        <section className="mb-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Metric title="评测集完成" value={`${summary.total}`} note={profile.purpose} />
          <Metric title="绿色通过" value={`${summary.counts.green}`} note="定向集结果，不代表线上发生率" />
          <Metric title="发布红线" value={`${summary.redlines}`} note="必须归零后再发布" danger />
          <Metric title="待 PM 复核" value={`${summary.review_queue}`} note="补证据或完成人工裁决" />
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
          <Card className="overflow-hidden py-0 shadow-sm">
            <CardHeader className="border-b py-5">
              <CardTitle>模型验收结果</CardTitle>
              <CardDescription>U / P / B = 用户价值 / 产品可信 / 业务可上线</CardDescription>
            </CardHeader>
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead className="pl-5">Case</TableHead>
                  <TableHead>场景</TableHead>
                  <TableHead>结果</TableHead>
                  <TableHead className="min-w-[250px]">自动判断</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((item) => (
                  <TableRow key={item.case_id}>
                    <TableCell className="pl-5 font-mono text-xs font-medium">{item.case_id}</TableCell>
                    <TableCell>{item.category_name}</TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={statusStyle[item.status as keyof typeof statusStyle]}
                      >
                        {item.status} · {item.scores.user_value ?? '—'}/{item.scores.product_trust ?? '—'}/
                        {item.scores.business_acceptability ?? '—'}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[420px] whitespace-normal text-muted-foreground">
                      {item.issue_codes.join(' · ') || item.evidence[0]}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle>交给算法团队的下一步</CardTitle>
              <CardDescription>按发布风险排序，不让平均分稀释红线</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {insights.top_priorities.slice(0, 4).map((item, index) => (
                <div key={item.issue_code} className="flex gap-3 border-b pb-4 last:border-0 last:pb-0">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-secondary font-mono text-xs font-semibold text-primary">
                    {index + 1}
                  </span>
                  <div>
                    <p className="font-mono text-xs font-semibold">{item.issue_code}</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.action}</p>
                    <p className="mt-1 text-xs text-primary">Owner · {item.owner}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}

function ProductStage({
  step,
  icon,
  title,
  description,
  inputs,
  output,
}: {
  step: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  inputs: string;
  output: string;
}) {
  return (
    <Card className="relative min-h-[250px] overflow-hidden shadow-sm">
      <span className="absolute right-5 top-4 font-mono text-5xl font-semibold text-primary/10">{step}</span>
      <CardHeader>
        <span className="mb-2 grid size-10 place-items-center rounded-xl bg-secondary text-primary [&>svg]:size-5">
          {icon}
        </span>
        <CardTitle>{title}</CardTitle>
        <CardDescription className="max-w-sm leading-6">{description}</CardDescription>
      </CardHeader>
      <CardContent className="mt-auto space-y-2 text-xs">
        <p className="flex items-start gap-2 text-muted-foreground">
          <FileCheck2 className="mt-0.5 size-3.5 shrink-0" /> 输入 · {inputs}
        </p>
        <p className="flex items-start gap-2 font-medium text-foreground">
          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" /> 输出 · {output}
        </p>
      </CardContent>
    </Card>
  );
}

function Metric({ title, value, note, danger = false }: { title: string; value: string; note: string; danger?: boolean }) {
  return (
    <Card className="gap-3 py-5 shadow-sm">
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle className={`font-mono text-3xl ${danger ? 'text-rose-600' : ''}`}>{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs leading-5 text-muted-foreground">{note}</CardContent>
    </Card>
  );
}
