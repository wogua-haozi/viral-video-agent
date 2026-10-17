import Link from 'next/link';
import { ArrowRight, ArrowUpRight, AudioLines, BookOpen, Check, Compass, FileSearch, Quote, Target } from 'lucide-react';
import { LinkButton } from '@/components/ui';

const templates = [
  { title: '找到赛道的内容脉络', template: 'B站赛道爆款分析', description: '从代表视频中观察选题、标题与内容形态。', icon: Compass, number: '01' },
  { title: '读懂一个竞品账号', template: '竞品账号内容拆解', description: '明确账号定位，梳理值得参考的内容方法。', icon: Target, number: '02' },
  { title: '拆开标题的吸引力', template: '热门标题结构分析', description: '看清受众、承诺和标题钩子如何组合。', icon: Quote, number: '03' },
  { title: '为下一条内容找方向', template: '选题方向分析', description: '把样本中的线索，转成可以验证的选题。', icon: BookOpen, number: '04' },
  { title: '细读脚本与开场', template: '内容脚本深度分析', description: '关注口播与结构；转写能力可用时可选深度分析。', icon: AudioLines, number: '05' },
];

export default function HomePage() {
  return (
    <main>
      <section className="studio-hero overflow-hidden border-b">
        <div className="mx-auto max-w-7xl px-5 pb-14 pt-7 sm:px-8 sm:pb-20 lg:px-10">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#c8a26b]/25 pb-5 font-mono text-[10px] uppercase tracking-[.2em] text-[#c9b99f]">
            <span>Viral Video Agent · The creator’s study</span><span>Bilibili / Public research</span>
          </div>
          <div className="grid gap-12 pt-14 lg:grid-cols-[1.08fr_.92fr] lg:items-center lg:gap-14 lg:pt-20">
            <div className="motion-enter">
              <p className="eyebrow">内容值得细看，判断需要来处。</p>
              <h1 className="title-balance mt-6 font-display text-4xl font-medium leading-[1.3] tracking-[.025em] sm:text-5xl lg:text-6xl">让真实样本，<br />照见<span className="text-[#ddb976]">创作方向。</span></h1>
              <p className="mt-7 max-w-lg text-pretty text-base leading-8 text-[#cec0aa] sm:text-lg">从一个赛道、一个账号，或一个内容问题开始。将 B 站公开样本整理成有出处、可回看的研究报告。</p>
              <div className="mt-9 flex flex-wrap gap-3">
                <LinkButton href="/jobs/new" size="lg" className="border-[#d8b477] bg-[#d8b477] text-[#251b10] shadow-none hover:bg-[#e6c894]">开始一次研究<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton>
                <LinkButton href="/examples" variant="secondary" size="lg" className="border-[#b69a70]/45 bg-transparent text-[#eee3cf] shadow-none hover:bg-white/5 hover:border-[#d8b477]">翻阅示例</LinkButton>
              </div>
              <div className="mt-9 flex flex-wrap gap-x-6 gap-y-3 text-xs text-[#beaf97]">{['B 站公开样本', '结论关联来源', '保留研究局限'].map((item) => <span key={item} className="inline-flex items-center gap-2"><Check className="h-3.5 w-3.5 text-[#d8b477]" aria-hidden="true" />{item}</span>)}</div>
            </div>

            <div className="motion-enter-delay relative lg:pl-5">
              <div className="studio-frame relative bg-[#2b2117] px-6 pb-7 pt-6 sm:px-8 sm:pb-9">
                <div className="flex items-center justify-between border-b border-[#cfad75]/25 pb-4"><span className="font-mono text-[10px] tracking-[.18em] text-[#c4a676]">RESEARCH NOTE / 001</span><span className="text-xs text-[#bcac93]">结构示例</span></div>
                <div className="my-7 flex items-start gap-4"><span className="font-display text-6xl leading-none text-[#bd945d]">“</span><h2 className="pt-1 font-display text-2xl leading-relaxed sm:text-3xl">一个好标题，<br />先让谁看见什么？</h2></div>
                <p className="border-l border-[#d0ac72]/60 pl-5 text-sm leading-7 text-[#d4c5ad]">把标题中的受众、任务和结果逐项拆开，再回到原视频核对。</p>
                <div className="mt-8 grid grid-cols-3 divide-x divide-[#cfad75]/20 border-y border-[#cfad75]/25 py-5">{[['观察', '真实样本'], ['推断', '解释线索'], ['建议', '下一次验证']].map(([title, text]) => <div key={title} className="px-3 first:pl-0"><p className="font-display text-xl text-[#e4c492]">{title}</p><p className="mt-2 text-[11px] text-[#beaf97]">{text}</p></div>)}</div>
                <div className="mt-6 flex items-center gap-3 text-xs text-[#c7b495]"><FileSearch className="h-4 w-4 shrink-0" aria-hidden="true" /><p className="leading-6">正式报告保留来源链接与采集时间。<br />本页示意不代表实际分析结论。</p></div>
              </div>
              <p className="mt-4 text-right font-display text-sm italic tracking-wide text-[#ae9677]">Evidence before conclusions.</p>
            </div>
          </div>
        </div>
      </section>

      <section id="templates" className="mx-auto max-w-7xl scroll-mt-24 px-5 py-14 sm:px-8 sm:py-20 lg:px-10">
        <div className="flex flex-col justify-between gap-5 border-b pb-7 sm:flex-row sm:items-end"><div><p className="eyebrow">Choose your inquiry</p><h2 className="section-heading mt-3">从你关心的问题开始。</h2></div><p className="max-w-sm text-sm leading-7 text-muted-foreground">选择一个起点，填入研究对象。<br />也可以直接用自己的话描述需求。</p></div>
        <div className="mt-2 grid md:grid-cols-2">{templates.map(({ title, template, description, icon: Icon, number }, index) => <Link key={template} href={`/jobs/new?template=${encodeURIComponent(template)}`} className={`group flex min-w-0 items-start gap-5 border-b py-7 transition-colors hover:bg-primary/[.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:gap-6 ${index % 2 === 0 ? 'md:pr-8' : 'md:border-l md:pl-8'}`}><span className="mt-1 font-mono text-xs text-primary">{number}</span><div className="min-w-0 flex-1"><div className="mb-4 flex items-center justify-between"><Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" /><ArrowUpRight className="h-4 w-4 text-primary transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" /></div><h3 className="font-display text-xl font-semibold">{title}</h3><p className="mt-3 text-sm leading-7 text-muted-foreground">{description}</p></div></Link>)}</div>
      </section>

      <section id="evidence" className="scroll-mt-24 border-y bg-surface">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-14 sm:px-8 sm:py-16 lg:grid-cols-[.9fr_1.1fr] lg:px-10"><div><p className="eyebrow">The method</p><h2 className="section-heading mt-4">把判断放回证据之中。</h2><p className="mt-5 max-w-md text-sm leading-8 text-muted-foreground">报告区分数据观察、分析推断与行动建议。样本不足时说明局限，让你知道一条建议建立在什么基础上。</p></div><ol className="divide-y border-t">{[['描述研究范围', '写清主题、账号、时间和关心的问题。'], ['整理公开样本', '能力开启时，先补充范围并确认候选账号。'], ['回看证据与结论', '核对实际数据、来源链接，再决定下一步。']].map(([title, description], index) => <li key={title} className="flex gap-5 py-5"><span className="pt-1 font-mono text-xs text-primary">0{index + 1}</span><div><h3 className="font-display text-lg font-semibold">{title}</h3><p className="mt-2 text-sm leading-7 text-muted-foreground">{description}</p></div></li>)}</ol></div>
      </section>
      <footer className="mx-auto flex max-w-7xl flex-col justify-between gap-5 px-5 py-9 text-xs text-muted-foreground sm:flex-row sm:items-center sm:px-8 lg:px-10"><p>爆款视频分析 · 专注 B 站公开内容研究</p><Link href="/jobs/new" className="inline-flex min-h-11 items-center gap-3 font-semibold text-primary">打开你的工作台<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link></footer>
    </main>
  );
}
