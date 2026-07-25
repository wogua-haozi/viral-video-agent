'use client';

import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, PencilLine, RotateCcw, Square } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { CandidateConfirmation } from '@/components/CandidateConfirmation';
import { JobProgress } from '@/components/product';
import { Button, Card, ErrorState, LoadingState, StatusBadge, Textarea } from '@/components/ui';
import { answerJobClarification, cancelJob, getJob, getJobCandidates, getJobClarification, getJobEvents, readableError, retryJob, reviseJob, type CandidateSnapshot, type ClarificationRequest, type Job, type JobEvent } from '@/lib/api';

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const revisionMode = searchParams.get('revise') === '1';
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [clarification, setClarification] = useState<ClarificationRequest | null>(null);
  const [clarificationHistory, setClarificationHistory] = useState<ClarificationRequest[]>([]);
  const [candidateSnapshot, setCandidateSnapshot] = useState<CandidateSnapshot | null>(null);
  const [selectedOption, setSelectedOption] = useState('');
  const [customAnswer, setCustomAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [answerError, setAnswerError] = useState('');
  const [retryError, setRetryError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const [showRevision, setShowRevision] = useState(revisionMode);
  const [revisionQuery, setRevisionQuery] = useState('');
  const [revisionError, setRevisionError] = useState('');
  const [revising, setRevising] = useState(false);
  const revisionKey = useRef('');

  const load = useCallback(async () => {
    try {
      const [jobData, eventData] = await Promise.all([getJob(id), getJobEvents(id)]);
      setJob(jobData);
      setEvents(eventData.items);
      const clarificationData = jobData.clarification_round > 0 ? await getJobClarification(id) : null;
      setClarification(jobData.status === 'waiting_user' ? clarificationData?.current || null : null);
      setClarificationHistory(clarificationData?.history || []);
      if (jobData.status === 'waiting_candidate_confirmation') setCandidateSnapshot(await getJobCandidates(id));
      else setCandidateSnapshot(null);
      if (revisionMode) {
        setShowRevision(true);
        setRevisionQuery((current) => current || jobData.query);
      }
      setError('');
      if (!revisionMode && jobData.report_id && ['completed', 'partial'].includes(jobData.status)) router.replace(`/reports/${jobData.report_id}`);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  }, [id, revisionMode, router]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, [load]);

  const cancel = async () => { setJob(await cancelJob(id)); await load(); };
  const retry = async () => {
    setRetrying(true);
    setRetryError('');
    try {
      const updated = await retryJob(id);
      router.replace(`/jobs/${updated.id}`);
    } catch (err) {
      setRetryError(readableError(err));
      await load();
    } finally {
      setRetrying(false);
    }
  };
  const openRevision = () => { if (!job) return; setRevisionQuery(job.query); setRevisionError(''); setShowRevision(true); };
  const revise = async () => {
    if (!job || !revisionQuery.trim() || revisionQuery.trim() === job.query.trim()) return;
    setRevising(true);
    setRevisionError('');
    if (!revisionKey.current) revisionKey.current = crypto.randomUUID();
    try {
      const revised = await reviseJob(id, { query: revisionQuery.trim(), idempotency_key: revisionKey.current });
      router.replace(`/jobs/${revised.id}`);
    } catch (err) {
      setRevisionError(readableError(err));
    } finally {
      setRevising(false);
    }
  };
  const answer = async () => {
    if (!clarification || (!selectedOption && !customAnswer.trim())) return;
    setSubmitting(true);
    setAnswerError('');
    try {
      await answerJobClarification(id, {
        request_id: clarification.request_id,
        ...(selectedOption ? { selected_option_id: selectedOption } : {}),
        ...(customAnswer.trim() ? { custom_answer: customAnswer.trim() } : {}),
      });
      setSelectedOption('');
      setCustomAnswer('');
      await load();
    } catch (err) {
      setAnswerError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl">
        {loading ? <LoadingState label="正在读取任务状态" /> : error ? <ErrorState description={error} action={<Button onClick={load}>重新读取</Button>} /> : job && (
          <>
            <Link href="/history" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="h-4 w-4" aria-hidden="true" />返回任务列表</Link>
            <div className="mt-4 grid gap-5 border-b pb-7 sm:grid-cols-[1fr_auto] sm:items-start">
              <div className="min-w-0"><p className="eyebrow">Live job / {job.id.slice(0, 6)}</p><h1 className="break-content title-balance mt-2 text-2xl font-black tracking-[-.035em] sm:text-3xl">{job.query}</h1><div className="mt-4 flex flex-wrap items-center gap-3"><StatusBadge status={job.status} /><span className="font-mono text-xs tabular-nums text-muted-foreground">进度 {job.progress}%</span><span className="text-xs text-muted-foreground">B站 · {job.analysis_mode === 'deep' ? '内容深度分析' : '标准分析'}</span></div></div>
              <div className="grid justify-items-start gap-2 sm:justify-items-end"><div className="flex flex-wrap gap-2">{['pending', 'running', 'waiting_user', 'waiting_candidate_confirmation'].includes(job.status) && <Button variant="danger" size="sm" onClick={cancel}><Square className="h-3.5 w-3.5" aria-hidden="true" />取消任务</Button>}{job.can_retry && <Button size="sm" onClick={retry} isLoading={retrying}><RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />重新分析</Button>}{job.can_revise && <Button variant="secondary" size="sm" onClick={openRevision}><PencilLine className="h-3.5 w-3.5" aria-hidden="true" />修改范围</Button>}</div>{retryError && <p className="max-w-sm text-sm text-destructive" role="alert">{retryError}</p>}</div>
            </div>

            {job.revision_of_job_id && <p className="mt-4 text-sm text-muted-foreground">修订自 <Link href={`/jobs/${job.revision_of_job_id}`} className="font-mono font-semibold text-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{job.revision_of_job_id.slice(0, 8)}</Link></p>}

            {showRevision && job.can_revise && (
              <Card className="mt-6 p-5 sm:p-6">
                <p className="eyebrow">范围修订</p>
                <h2 className="mt-2 text-lg font-bold">创建修订任务</h2>
                <p className="mt-1 text-sm text-muted-foreground">旧任务和回答会保留。</p>
                <label htmlFor="revision-query" className="mt-4 block text-sm font-semibold">新的研究范围</label>
                <Textarea id="revision-query" className="mt-2 min-h-24" maxLength={2000} value={revisionQuery} onChange={(event) => setRevisionQuery(event.target.value)} />
                {revisionError && <p className="mt-2 text-sm text-destructive" role="alert">{revisionError}</p>}
                <div className="mt-3 flex flex-wrap gap-2"><Button onClick={revise} isLoading={revising} disabled={!revisionQuery.trim() || revisionQuery.trim() === job.query.trim()}>创建修订任务</Button><Button variant="ghost" onClick={() => setShowRevision(false)} disabled={revising}>取消</Button></div>
              </Card>
            )}

            {job.status === 'waiting_user' && clarification && (
              <Card className="mt-6 p-5 sm:p-6">
                <p className="eyebrow">补充范围 · {clarification.round}/2</p>
                <h2 id="clarification-question" className="mt-2 text-lg font-bold">{clarification.question}</h2>
                <fieldset className="mt-4 grid gap-2" aria-labelledby="clarification-question">
                  <legend className="sr-only">选择研究范围</legend>
                  {clarification.options.map((option) => (
                    <label key={option.id} className="flex cursor-pointer gap-3 rounded-lg border p-3 hover:border-primary/40">
                      <input type="radio" name="clarification" value={option.id} checked={selectedOption === option.id} onChange={() => setSelectedOption(option.id)} className="mt-1 accent-primary" />
                      <span><strong className="block text-sm">{option.label}</strong><span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{option.description}</span></span>
                    </label>
                  ))}
                </fieldset>
                {clarification.allow_custom && <><label htmlFor="clarification-custom-answer" className="sr-only">补充说明（可选）</label><Textarea id="clarification-custom-answer" className="mt-3 min-h-20" maxLength={2000} value={customAnswer} onChange={(event) => setCustomAnswer(event.target.value)} placeholder="补充说明（可选）" /></>}
                {answerError && <p className="mt-2 text-sm text-destructive" role="alert">{answerError}</p>}
                <Button className="mt-3" onClick={answer} isLoading={submitting} disabled={!selectedOption && !customAnswer.trim()}>提交并继续</Button>
              </Card>
            )}

            {job.status === 'waiting_candidate_confirmation' && job.can_confirm_candidates && candidateSnapshot && (
              <CandidateConfirmation key={candidateSnapshot.snapshot_id} jobId={job.id} snapshot={candidateSnapshot} onSubmitted={load} />
            )}

            {clarificationHistory.length > 0 && (
              <section className="mt-7" aria-labelledby="clarification-history-title">
                <p className="eyebrow">Clarification history</p>
                <h2 id="clarification-history-title" className="mt-1 text-xl font-black">澄清记录</h2>
                <div className="mt-3 grid gap-3">
                  {clarificationHistory.map((item) => {
                    const selected = item.options.find((option) => option.id === item.selected_option_id)?.label;
                    return <Card key={item.request_id} className="p-4 sm:p-5"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-mono text-xs text-muted-foreground">第 {item.round} 轮</p><span className="text-xs font-semibold text-success">已回答</span></div><h3 className="mt-2 text-sm font-bold">{item.question}</h3>{selected && <p className="mt-2 text-sm text-foreground">{selected}</p>}{item.custom_answer && <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.custom_answer}</p>}</Card>;
                  })}
                </div>
              </section>
            )}

            <Card className="mt-7 overflow-hidden p-0">
              <div className="bg-secondary px-5 py-5 text-secondary-foreground sm:px-7"><div className="flex items-center justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary">Execution timeline</p><h2 className="mt-1 font-bold">任务执行进度</h2></div><span className="font-mono text-2xl font-black tabular-nums">{job.progress}%</span></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-label="任务执行进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress}><div className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-[width]" style={{ width: `${job.progress}%` }} /></div></div>
              <div className="p-5 sm:p-7"><JobProgress status={job.status} events={events} /></div>
            </Card>

            {job.error_message && <Card className="mt-4 border-destructive/30 p-5"><p className="eyebrow text-destructive">Job interrupted</p><h2 className="mt-1 font-bold text-destructive">任务未完成</h2><p className="break-content mt-2 text-sm leading-6 text-muted-foreground">{job.error_message}</p><p className="mt-3 font-mono text-xs text-muted-foreground">{job.error_code}</p></Card>}
            <p className="mt-5 text-center text-xs text-muted-foreground">可安全刷新，任务状态已持久化。</p>
          </>
        )}
      </div>
    </AppShell>
  );
}
