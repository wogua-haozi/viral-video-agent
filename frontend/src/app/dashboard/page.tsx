'use client';

import Link from 'next/link';
import { ArrowRight, ArrowUpRight, Clock3, FilePlus2 } from 'lucide-react';
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
      <section className="mb-10 pt-1 sm:pt-3">
        <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-center">
          <div><h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">工作台</h1><p className="mt-3 text-sm leading-7 text-muted-foreground">继续已有研究，或开始一个新问题。</p></div>
          <LinkButton href="/jobs/new" className="self-start sm:self-auto"><FilePlus2 className="h-4 w-4" aria-hidden="true" />新建研究</LinkButton>
        </div>
      </section>
      {loading ? <LoadingState label="正在整理你的研究记录" /> : error ? <ErrorState description={error} action={<Button onClick={load}>重新读取</Button>} /> : (
        <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="min-w-0 space-y-9">
            {attention.length > 0 && <section aria-labelledby="attention-title" className="rounded-2xl bg-primary/5 p-5 sm:p-6"><div className="mb-2 flex items-center gap-2"><Clock3 className="h-4 w-4 text-primary" aria-hidden="true" /><h2 id="attention-title" className="text-base font-semibold">需要你继续</h2></div><div className="divide-y">{attention.map((job) => <Link key={job.id} href={`/jobs/${job.id}`} className="flex min-h-14 items-center justify-between gap-4 rounded-sm py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><div className="min-w-0"><p className="break-content text-sm font-medium">{job.query}</p><p className="mt-1 text-xs leading-6 text-muted-foreground">{job.status === 'waiting_user' ? '补充研究范围后，任务会继续' : '确认哪些账号应纳入这次分析'}</p></div><ArrowRight className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" /></Link>)}</div><Link href="/history" className="mt-2 inline-flex min-h-11 items-center rounded-sm text-xs font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">查看全部任务</Link></section>}
            <section aria-labelledby="recent-jobs-title"><div className="mb-4 flex items-center justify-between gap-4"><h2 id="recent-jobs-title" className="text-xl font-semibold tracking-tight">最近的研究</h2><Link href="/history" className="inline-flex min-h-11 items-center gap-1.5 rounded-sm text-xs font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">全部记录<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link></div><div className="space-y-3">{jobs.length ? jobs.map((job) => <JobSummaryCard key={job.id} id={job.id} title={job.query} status={job.status} progress={job.progress} createdAt={job.created_at} />) : <Card><EmptyState title="开始你的第一篇研究" description="例如：研究 B 站近 30 天的 AI 编程教程，重点看标题与开场。" action={<LinkButton href="/jobs/new">写下第一个问题</LinkButton>} /></Card>}</div></section>
          </div>
          <aside className="space-y-8">
            {usage && <UsageCard usage={usage} />}
            <section><h2 className="mb-2 text-base font-semibold">研究起点</h2><div className="divide-y">{templates.map(([template, title, description]) => <Link key={template} href={`/jobs/new?template=${encodeURIComponent(template)}`} className="group flex items-center justify-between gap-3 rounded-sm py-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><div><h3 className="text-sm font-medium group-hover:text-primary">{title}</h3><p className="mt-1 text-xs leading-6 text-muted-foreground">{description}</p></div><ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" aria-hidden="true" /></Link>)}</div></section>
          </aside>
        </div>
      )}
    </AppShell>
  );
}
