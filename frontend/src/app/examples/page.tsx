import Link from 'next/link';
import { ArrowRight, FileText, ShieldCheck } from 'lucide-react';
import { Card, LinkButton } from '@/components/ui';

const examples = [{ id: 'bilibili-ai-programming', title: 'B站 AI 编程赛道内容分析示例', summary: '展示真实来源、结构化结论、Evidence 引用和数据附录的报告形态。', tag: '赛道分析' }];

export default function ExamplesPage() {
  return (
    <main className="min-h-[calc(100dvh-4rem)] border-b">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8 lg:py-20">
        <div className="grid gap-8 border-b pb-9 lg:grid-cols-[.8fr_1.2fr] lg:items-end">
          <div><p className="eyebrow">报告示例</p><h1 className="title-balance mt-3 font-display text-4xl font-semibold leading-snug sm:text-5xl">先看清证据如何进入报告</h1></div>
          <div className="lg:justify-self-end"><p className="max-w-xl text-pretty leading-7 text-muted-foreground">示例用于展示产品结构，不代表实时市场结论。公开测试生成的报告会使用当次任务的真实 Evidence。</p><div className="mt-4 inline-flex items-center gap-2 text-xs font-semibold text-success"><ShieldCheck className="h-4 w-4" aria-hidden="true" />单平台边界与来源标记保持可见</div></div>
        </div>

        <div className="mt-8 grid gap-5 md:grid-cols-2">
          {examples.map((item, index) => (
            <Link key={item.id} href={`/examples/${item.id}`} className="group rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
              <Card className="relative min-h-64 overflow-hidden p-6 transition-[border-color,box-shadow] group-hover:border-primary/40 group-hover:shadow-float sm:p-7">
                <div className="absolute right-0 top-0 h-full w-24 bg-primary/5 [clip-path:polygon(100%_0,100%_100%,20%_100%,0_0)]" aria-hidden="true" />
                <div className="relative flex items-start justify-between gap-4"><span className="grid h-12 w-12 place-items-center rounded-xl border bg-primary/10 text-primary"><FileText className="h-5 w-5" aria-hidden="true" /></span><span className="editorial-number">REPORT / 0{index + 1}</span></div>
                <div className="relative mt-8"><span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary">{item.tag}</span><h2 className="title-balance mt-3 text-2xl font-bold tracking-[-.03em]">{item.title}</h2><p className="mt-3 max-w-xl text-pretty text-sm leading-6 text-muted-foreground">{item.summary}</p><span className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-primary">打开示例<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span></div>
              </Card>
            </Link>
          ))}
        </div>
        <div className="mt-10"><LinkButton href="/register">创建自己的报告<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton></div>
      </div>
    </main>
  );
}
