'use client';

import Link from 'next/link';
import { ArrowRight, Filter, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Button, Card, EmptyState, ErrorState, Input, LinkButton, LoadingState, Select, StatusBadge } from '@/components/ui';
import { deleteJob, listJobs, readableError, retryJob, type Job } from '@/lib/api';

export default function HistoryPage() {
  const [items, setItems] = useState<Job[]>([]);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retryingId, setRetryingId] = useState('');
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    listJobs('?limit=100').then((data) => setItems(data.items)).catch((err) => setError(readableError(err))).finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);
  const filtered = useMemo(() => items.filter((job) => (!search || job.query.toLowerCase().includes(search.toLowerCase())) && (status === 'all' || job.status === status) && (!date || job.created_at.startsWith(date))), [items, search, status, date]);

  const remove = async (id: string) => {
    if (!confirm('删除该任务及其报告？此操作不可撤销。')) return;
    try {
      await deleteJob(id);
      setItems((current) => current.filter((item) => item.id !== id));
    } catch (err) {
      setError(readableError(err));
    }
  };

  const retry = async (id: string) => {
    setRetryingId(id);
    setRetryErrors((current) => ({ ...current, [id]: '' }));
    try {
      const job = await retryJob(id);
      window.location.href = `/jobs/${job.id}`;
    } catch (err) {
      setRetryErrors((current) => ({ ...current, [id]: readableError(err) }));
      load();
    } finally {
      setRetryingId('');
    }
  };

  return (
    <AppShell>
      <div className="mb-7 grid gap-5 border-b pb-7 sm:grid-cols-[1fr_auto] sm:items-end">
        <div><p className="eyebrow">Archive / 03</p><h1 className="title-balance mt-2 font-display text-3xl font-semibold leading-snug sm:text-4xl">任务与报告</h1><p className="mt-2 text-sm text-muted-foreground">按关键词、状态和日期查找历史研究。</p></div>
        <LinkButton href="/jobs/new">新建分析<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton>
      </div>

      <Card className="mb-6 p-4 sm:p-5">
        <div className="mb-4 flex items-center gap-2 border-b pb-3"><Filter className="h-4 w-4 text-primary" aria-hidden="true" /><span className="eyebrow">Filters</span></div>
        <div className="grid gap-4 md:grid-cols-[1fr_13rem_13rem]">
          <label className="text-sm font-semibold">搜索关键词<div className="relative mt-2"><Search className="pointer-events-none absolute left-3.5 top-4 h-4 w-4 text-muted-foreground" aria-hidden="true" /><Input className="pl-10" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="输入赛道、选题或竞品" /></div></label>
          <label className="text-sm font-semibold">任务状态<Select className="mt-2" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="completed">已完成</option><option value="partial">部分完成</option><option value="waiting_user">待补充</option><option value="waiting_candidate_confirmation">待确认候选</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="running">分析中</option><option value="pending">排队中</option></Select></label>
          <label className="text-sm font-semibold">创建日期<Input className="mt-2" type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        </div>
      </Card>

      {loading ? <LoadingState label="正在读取历史任务" /> : error ? <ErrorState description={error} action={<Button onClick={load}>重试</Button>} /> : filtered.length === 0 ? <Card><EmptyState title="没有符合条件的记录" description="调整筛选条件，或创建新的 B 站分析任务。" action={<Button variant="secondary" onClick={() => { setSearch(''); setStatus('all'); setDate(''); }}>清除筛选</Button>} /></Card> : (
        <div className="space-y-3">
          {filtered.map((job, index) => (
            <Card key={job.id} className="p-4 sm:p-5">
              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                <Link href={job.report_id ? `/reports/${job.report_id}` : `/jobs/${job.id}`} className="group min-w-0 flex-1 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <div className="flex flex-wrap items-center gap-3"><span className="editorial-number">{String(index + 1).padStart(2, '0')}</span><StatusBadge status={job.status} /><span className="font-mono text-[11px] tabular-nums text-muted-foreground">{new Date(job.created_at).toLocaleString('zh-CN')}</span></div>
                  <p className="break-content mt-3 font-bold leading-6 transition-colors group-hover:text-primary">{job.query}</p>
                  <p className="mt-1 text-xs text-muted-foreground">B站 · {job.analysis_mode === 'deep' ? '内容深度分析' : '标准分析'} · 进度 {job.progress}%</p>
                </Link>
                <div className="grid justify-items-start gap-2 sm:justify-items-end"><div className="flex flex-wrap gap-2">{job.can_retry && <Button variant="secondary" size="sm" onClick={() => retry(job.id)} isLoading={retryingId === job.id}>重试</Button>}<Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => remove(job.id)} disabled={retryingId === job.id || job.is_stopping}>{job.is_stopping ? '停止中' : '删除'}</Button></div>{retryErrors[job.id] && <p className="max-w-xs text-sm text-destructive" role="alert">{retryErrors[job.id]}</p>}</div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}
