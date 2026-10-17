'use client';

import Link from 'next/link';
import { ArrowRight, ArrowUpRight, Clock3, FilePlus2, NotebookPen } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { JobSummaryCard, UsageCard } from '@/components/product';
import { Button, Card, EmptyState, ErrorState, LinkButton, LoadingState } from '@/components/ui';
import { getUsage, listJobs, readableError, type Job, type UsageSummary } from '@/lib/api';

const templates = [
  ['B站赛道爆款分析', '赛道观察', '找出代表内容与选题线索'],
  ['竞品账号内容拆解', '账号研究', '看清定位、选题与表达方式'],
  ['热门标题结构分析', '标题细读', '拆解受众、承诺与吸引力'],
  ['选题方向分析', '下一条内容', '找到值得验证的创作方向'],
];

export default function DashboardPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [attention, setAttention] = useState<Job[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setError('');
    try {
      const [jobData, usageData, briefData, candidateData] = await Promise.all([
        listJobs('?limit=6'), getUsage(), listJobs('?status=waiting_user&limit=5'), listJobs('?status=waiting_candidate_confirmation&limit=5'),
      ]);
      setJobs(jobData.items); setUsage(usageData); setAttention([...briefData.items, ...candidateData.items]);
    } catch (err) { setError(readableError(err)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <AppShell>
      <section className="studio-hero mb-8 overflow-hidden rounded-xl border p-6 sm:p-9">
        <div className="flex flex-col justify-between gap-7 xl:flex-row xl:items-end">
          <div><p className="eyebrow">Your research desk</p><h1 className="mt-4 font-display text-3xl font-medium leading-snug sm:text-4xl">下一条好内容，<br className="sm:hidden" />从一个好问题开始。</h1><p className="mt-4 max-w-xl text-sm leading-7 text-[#c9b99f]">你的研究、样本与创作线索，都留在这里。</p></div>
          <LinkButton href="/jobs/new" className="self-start border-[#d8b477] bg-[#d8b477] text-[#251b10] shadow-none hover:bg-[#e6c894]"><FilePlus2 className="h-4 w-4" aria-hidden="true" />新建研究</LinkButton>
        </div>
      </section>
      {loading ? <LoadingState label="正在整理你的研究记录" /> : error ? <ErrorState description={error} action={<Button onClick={load}>重新读取</Button>} /> : (
        <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 space-y-8">
            {attention.length > 0 && <section aria-labelledby="attention-title" className="rounded-xl border border-primary/35 bg-primary/5 p-5"><div className="mb-3 flex items-center gap-2"><Clock3 className="h-4 w-4 text-primary" aria-hidden="true" /><h2 id="attention-title" className="font-display text-lg font-semibold">需要你继续</h2></div><div className="divide-y">{attention.map((job) => <Link key={job.id} href={`/jobs/${job.id}`} className="flex min-h-14 items-center justify-between gap-4 rounded-sm py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><div className="min-w-0"><p className="break-content text-sm font-semibold">{job.query}</p><p className="mt-1 text-xs text-muted-foreground">{job.status === 'waiting_user' ? '补充研究范围后，任务会继续' : '确认哪些账号应纳入这次分析'}</p></div><ArrowRight className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" /></Link>)}</div><Link href="/history" className="mt-3 inline-flex min-h-11 items-center text-xs font-semibold text-primary underline underline-offset-4">查看全部任务</Link></section>}
            <section aria-labelledby="recent-jobs-title"><div className="mb-4 flex items-end justify-between gap-4 border-b pb-4"><div><p className="eyebrow">Research journal</p><h2 id="recent-jobs-title" className="mt-2 font-display text-2xl font-semibold">最近的研究</h2></div><Link href="/history" className="inline-flex min-h-11 items-center gap-2 rounded-sm text-xs font-semibold text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">全部记录<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link></div><div className="space-y-3">{jobs.length ? jobs.map((job) => <JobSummaryCard key={job.id} id={job.id} title={job.query} status={job.status} progress={job.progress} createdAt={job.created_at} />) : <Card><EmptyState title="第一篇研究，等你开始" description="例如：研究 B 站近 30 天的 AI 编程教程，重点看标题与开场。" action={<LinkButton href="/jobs/new">写下第一个问题</LinkButton>} /></Card>}</div></section>
          </div>
          <aside className="space-y-6">
            {usage && <UsageCard usage={usage} />}
            <section><div className="mb-3 flex items-center gap-2 border-b pb-4"><NotebookPen className="h-4 w-4 text-primary" aria-hidden="true" /><h2 className="font-display text-lg font-semibold">选一个研究起点</h2></div><div className="divide-y">{templates.map(([template, title, description], index) => <Link key={template} href={`/jobs/new?template=${encodeURIComponent(template)}`} className="group flex gap-4 rounded-sm py-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="mt-1 font-mono text-xs text-primary">0{index + 1}</span><div><h3 className="text-sm font-semibold group-hover:text-primary">{title}</h3><p className="mt-1.5 text-xs leading-6 text-muted-foreground">{description}</p></div></Link>)}</div></section>
          </aside>
        </div>
      )}
    </AppShell>
  );
}
