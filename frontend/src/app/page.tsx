import Link from 'next/link';
import { ArrowRight, ArrowUpRight, AudioLines, BookOpen, Compass, FileSearch, Quote, Target } from 'lucide-react';
import { LinkButton } from '@/components/ui';

const templates = [
  { title: '赛道观察', template: 'B站赛道爆款分析', description: '观察代表视频，梳理内容脉络。', icon: Compass },
  { title: '账号研究', template: '竞品账号内容拆解', description: '了解账号定位与内容方法。', icon: Target },
  { title: '标题分析', template: '热门标题结构分析', description: '拆解受众、承诺与吸引力。', icon: Quote },
  { title: '选题方向', template: '选题方向分析', description: '找到值得验证的创作方向。', icon: BookOpen },
  { title: '脚本拆解', template: '内容脚本深度分析', description: '细看开场与结构，可选深度转写。', icon: AudioLines },
];

export default function HomePage() {
  return (
    <main>
      <section className="bg-background">
        <div className="mx-auto max-w-7xl px-5 pb-16 pt-14 sm:px-8 sm:pb-24 sm:pt-20 lg:px-10">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-medium text-muted-foreground">为 B 站创作者而作</p>
            <h1 className="title-balance mt-5 text-4xl font-semibold leading-[1.25] tracking-tight sm:text-5xl lg:text-6xl">让真实样本，<br />带来清晰方向。</h1>
            <p className="mx-auto mt-6 max-w-xl text-pretty text-base leading-8 text-muted-foreground sm:text-lg">从一个内容问题开始，读懂公开样本。<br className="hidden sm:block" />将观察整理成有来源、可核对的研究报告。</p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <LinkButton href="/jobs/new" size="lg">开始一次研究<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton>
              <LinkButton href="/examples" variant="ghost" size="lg">浏览示例<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></LinkButton>
            </div>
          </div>

          <div className="mx-auto mt-12 max-w-4xl rounded-3xl border border-border/50 bg-card p-5 shadow-editorial sm:mt-16 sm:p-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-sm font-medium text-muted-foreground">报告预览</span>
              <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">结构示例</span>
            </div>
            <h2 className="mt-6 text-xl font-semibold leading-relaxed tracking-tight sm:text-2xl">一个好标题，如何吸引目标观众？</h2>
            <div className="mt-6 grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:gap-8">
              <div className="rounded-2xl bg-muted/60 p-5">
                <FileSearch className="h-5 w-5 text-muted-foreground" strokeWidth={1.5} aria-hidden="true" />
                <h3 className="mt-4 text-sm font-semibold">样本材料</h3>
                <p className="mt-2 text-sm leading-7 text-muted-foreground">标题与来源<br />发布时间与采集时间</p>
                <p className="mt-4 border-t border-border/60 pt-4 text-xs leading-6 text-muted-foreground">保留原始出处，供你逐项核对。</p>
              </div>
              <dl className="divide-y divide-border/60">
                {[
                  ['观察', '从样本中梳理标题的共同结构。'],
                  ['推断', '解释线索，并说明证据的局限。'],
                  ['建议', '形成下一次创作可以验证的方向。'],
                ].map(([title, description]) => <div key={title} className="py-4 first:pt-0 last:pb-0 md:first:pt-2"><dt className="text-sm font-semibold">{title}</dt><dd className="mt-1.5 text-sm leading-7 text-muted-foreground">{description}</dd></div>)}
              </dl>
            </div>
            <p className="mt-6 border-t border-border/60 pt-5 text-xs leading-6 text-muted-foreground">仅展示报告结构，不代表实际分析结论。正式报告保留来源链接与采集时间。</p>
          </div>
        </div>
      </section>

      <section id="templates" className="mx-auto max-w-7xl scroll-mt-24 px-5 pb-16 pt-4 sm:px-8 sm:pb-24 sm:pt-6 lg:px-10">
        <div className="mb-9 text-center"><h2 className="section-heading">你想研究什么？</h2><p className="mt-4 text-sm leading-7 text-muted-foreground">选一个起点，也可以用自己的话描述问题。</p></div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {templates.map(({ title, template, description, icon: Icon }) => (
            <Link key={template} href={`/jobs/new?template=${encodeURIComponent(template)}`} className="group min-w-0 rounded-2xl border border-border/50 bg-card p-5 transition-colors hover:border-border hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
              <div className="flex items-center justify-between"><Icon className="h-5 w-5 text-muted-foreground" strokeWidth={1.5} aria-hidden="true" /><ArrowUpRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" aria-hidden="true" /></div>
              <h3 className="mt-6 text-base font-semibold">{title}</h3><p className="mt-2 text-sm leading-7 text-muted-foreground">{description}</p>
            </Link>
          ))}
        </div>
      </section>

      <section id="evidence" className="scroll-mt-24 bg-surface">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24 lg:px-10">
          <div className="mx-auto max-w-xl text-center"><h2 className="section-heading">每个判断，都有来处。</h2><p className="mt-4 text-sm leading-8 text-muted-foreground">回到样本核对结论，了解研究的范围与局限，<br className="hidden sm:block" />再决定什么值得用于下一次创作。</p></div>
          <ol className="mt-12 grid gap-9 sm:grid-cols-3 sm:gap-10">
            {[
              ['描述研究范围', '写清主题、账号、时间和关心的问题。'],
              ['整理公开样本', '能力开启时，可补充范围并确认候选账号。'],
              ['核对来源与结论', '查看实际数据和来源；样本不足时，报告说明局限。'],
            ].map(([title, description], index) => <li key={title}><span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm tabular-nums text-muted-foreground">{index + 1}</span><h3 className="mt-4 text-base font-semibold">{title}</h3><p className="mt-2 text-sm leading-7 text-muted-foreground">{description}</p></li>)}
          </ol>
        </div>
      </section>
      <footer className="mx-auto flex max-w-7xl flex-col justify-between gap-3 border-t px-5 py-7 text-xs text-muted-foreground sm:flex-row sm:items-center sm:px-8 lg:px-10"><p>爆款视频分析 · B 站公开内容研究</p><Link href="/jobs/new" className="inline-flex min-h-11 items-center gap-2 rounded-sm font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">开始研究<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link></footer>
    </main>
  );
}
