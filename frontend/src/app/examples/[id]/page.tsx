import Link from 'next/link';
import { ArrowLeft, CheckCircle2, ExternalLink, Link2 } from 'lucide-react';
import { Card, LinkButton } from '@/components/ui';

export default function ExampleReportPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-12 lg:px-8">
      <Link href="/examples" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="h-4 w-4" aria-hidden="true" />返回示例</Link>
      <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0 space-y-5">
          <div className="border border-info/30 bg-info/10 p-4 text-sm text-foreground"><strong className="mr-2 text-info">结构示例</strong>以下内容不是实时市场数据，Evidence 卡片只展示正式报告的界面结构。</div>
          <Card className="print-card overflow-hidden p-0">
            <div className="border-b bg-secondary px-6 py-7 text-secondary-foreground sm:px-9"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary">报告示例</p><h1 className="title-balance mt-3 font-display text-3xl font-semibold leading-snug sm:text-4xl">B站 AI 编程赛道内容分析示例</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">用于说明结论层级、Evidence 引用与行动建议如何在同一份报告中协作。</p></div>
            <article className="report-prose p-6 sm:p-9">
              <h2>执行摘要</h2><p>示例报告把结论分为数据观察、分析推断和行动建议，并为所有数值结论绑定 Evidence 编号。</p>
              <h2>数据观察</h2><blockquote>代表样本的标题普遍明确指出工具、任务和结果。<a href="#example-evidence">[ev_example_01]</a></blockquote>
              <h2>分析推断</h2><p>受众可能更关注“能完成什么任务”，而不是单纯关注模型名称。该判断需要更多样本验证。</p>
              <h2>行动建议</h2><ol><li>标题先写具体工作任务，再写使用的技术。</li><li>用结果画面或对比画面作为开头。</li><li>发布后记录点击率与前 30 秒留存，形成下一轮证据。</li></ol>
            </article>
          </Card>
          <Card id="example-evidence" className="scroll-mt-24 overflow-hidden p-0">
            <div className="h-1 bg-primary" /><div className="p-5 sm:p-6"><div className="flex flex-wrap items-center gap-2"><span className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 font-mono text-[11px] font-semibold text-primary"><span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />ev_example_01</span><span className="rounded-full border bg-muted px-2.5 py-1 text-[11px] font-semibold text-muted-foreground">界面示例</span></div><h2 className="mt-4 text-lg font-bold">示例 Evidence 卡片</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">真实报告会在这里显示 BVID、标题、UP 主、来源 URL、抓取时间与可用数据字段。</p><div className="mt-5 grid border-t pt-4 text-xs text-muted-foreground sm:grid-cols-3"><span>平台：B站</span><span>字段：标题、作者、互动</span><span>来源：公开页面</span></div></div>
          </Card>
        </div>
        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <Card className="p-5"><p className="eyebrow">Report anatomy</p><h2 className="mt-2 font-bold">示例包含</h2><ul className="mt-4 space-y-3 text-sm text-muted-foreground">{['结论层级', 'Evidence 引用', '行动建议', '来源附录'].map((item) => <li key={item} className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />{item}</li>)}</ul></Card>
          <Card className="p-5"><div className="flex items-center gap-2 text-primary"><Link2 className="h-4 w-4" aria-hidden="true" /><span className="font-mono text-[10px] font-semibold uppercase tracking-[.12em]">Traceable</span></div><p className="mt-3 text-sm leading-6 text-muted-foreground">正式报告中的引用会跳转到对应 Evidence，并允许打开真实来源。</p></Card>
          <LinkButton href="/register" className="w-full">创建报告<ExternalLink className="h-4 w-4" aria-hidden="true" /></LinkButton>
        </aside>
      </div>
    </main>
  );
}
