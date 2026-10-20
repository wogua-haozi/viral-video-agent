'use client';

import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, PencilLine, RefreshCw, RotateCcw, Square } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { CandidateConfirmation } from '@/components/CandidateConfirmation';
import { JobProgress } from '@/components/product';
import { Button, Card, ErrorState, LoadingState, StatusBadge, Textarea } from '@/components/ui';
import { ApiError, answerJobClarification, cancelJob, getCurrentUser, getJob, getJobCandidates, getJobClarification, getJobEvents, readableError, retryJob, reviseJob, type CandidateSnapshot, type ClarificationRequest, type Job, type JobEvent } from '@/lib/api';
import { clearRevisionAttempt, readRevisionAttempts, RevisionStorageError, saveRevisionAttempt } from '@/lib/revision-attempt';

const RETRY_CONFIRMATION_MS = 20_000;
const RETRY_REJECTION_CODES = new Set(['JOB_NOT_FOUND', 'JOB_STOPPING', 'JOB_RETRY_LIMIT_REACHED', 'JOB_NOT_RETRYABLE', 'AUTH_REQUIRED']);

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
  const [refreshError, setRefreshError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [pollingEpoch, setPollingEpoch] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState('');
  const [answerError, setAnswerError] = useState('');
  const [retryError, setRetryError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const [reconcilingRetry, setReconcilingRetry] = useState(false);
  const [retryUnconfirmed, setRetryUnconfirmed] = useState(false);
  const retryVersion = useRef<number | null>(null);
  const retryDeadline = useRef<number | null>(null);
  const [showRevision, setShowRevision] = useState(revisionMode);
  const [revisionQuery, setRevisionQuery] = useState('');
  const [revisionError, setRevisionError] = useState('');
  const [revising, setRevising] = useState(false);
  const [revisionUserId, setRevisionUserId] = useState<string | null>(null);
  const [revisionIdentityEpoch, setRevisionIdentityEpoch] = useState(0);
  const jobRef = useRef<Job | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const signal = controller.signal;
    try {
      const jobData = await getJob(id, signal);
      if (signal.aborted) return;
      jobRef.current = jobData;
      setJob(jobData);
      setError('');
      if (retryVersion.current !== null && jobData.execution_version > retryVersion.current) {
        setRetryError('');
        retryVersion.current = null;
        retryDeadline.current = null;
        setReconcilingRetry(false);
        setRetryUnconfirmed(false);
      }
      if (jobData.status !== 'waiting_candidate_confirmation') setCandidateSnapshot(null);
      if (jobData.status !== 'waiting_user') setClarification(null);
      const [eventResult, briefResult, candidateResult] = await Promise.allSettled([
        getJobEvents(id, signal),
        jobData.clarification_round > 0 ? getJobClarification(id, signal) : Promise.resolve(null),
        jobData.status === 'waiting_candidate_confirmation' ? getJobCandidates(id, signal) : Promise.resolve(null),
      ]);
      if (signal.aborted) return;
      if (eventResult.status === 'fulfilled') setEvents(eventResult.value.items);
      if (briefResult.status === 'fulfilled') {
        setClarification(jobData.status === 'waiting_user' ? briefResult.value?.current || null : null);
        setClarificationHistory(briefResult.value?.history || []);
      }
      if (candidateResult.status === 'fulfilled') setCandidateSnapshot(candidateResult.value);
      const failed = [eventResult, briefResult, candidateResult].find((result) => result.status === 'rejected');
      setRefreshError(failed?.status === 'rejected' ? readableError(failed.reason) : '');
      setLastUpdated(new Date());
      if (revisionMode) {
        setRevisionQuery((current) => current || jobData.query);
      }
      if (!revisionMode && jobData.report_id && ['completed', 'partial'].includes(jobData.status)) router.replace(`/reports/${jobData.report_id}`);
      return jobData;
    } catch (err) {
      if (signal.aborted) return;
      // A background refresh must never unmount an in-progress confirmation form.
      if (jobRef.current) setRefreshError(readableError(err));
      else setError(readableError(err));
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [id, revisionMode, router]);

  useEffect(() => {
    let disposed = false;
    setRevisionUserId(null);
    setRevisionQuery('');
    setRevisionError('');
    setShowRevision(revisionMode);
    void getCurrentUser().then((user) => {
      if (disposed) return;
      const attempts = readRevisionAttempts(user.id, id);
      const latest = attempts[attempts.length - 1];
      setRevisionUserId(user.id);
      if (latest) { setRevisionQuery(latest.query); setShowRevision(true); }
      else setRevisionQuery((current) => current || jobRef.current?.query || '');
    }).catch((err) => { if (!disposed) setRevisionError(err instanceof RevisionStorageError ? err.message : readableError(err)); });
    return () => { disposed = true; };
  }, [id, revisionMode, revisionIdentityEpoch]);

  useEffect(() => {
    jobRef.current = null;
    setJob(null);
    setLoading(true);
    setError('');
    setRefreshError('');
    setCandidateSnapshot(null);
    setSelectedOption('');
    setCustomAnswer('');
    retryVersion.current = null;
    retryDeadline.current = null;
    setRetryError('');
    setReconcilingRetry(false);
    setRetryUnconfirmed(false);
  }, [load]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let confirmationTimer: ReturnType<typeof setTimeout> | undefined;
    let pollVersion = 0;
    if (retryDeadline.current !== null) {
      confirmationTimer = setTimeout(() => {
        if (retryVersion.current === null) return;
        retryDeadline.current = null;
        setReconcilingRetry(false);
        setRetryUnconfirmed(true);
        setLoading(false);
        ++pollVersion;
        clearTimeout(timer);
        controllerRef.current?.abort();
      }, Math.max(0, retryDeadline.current - Date.now()));
    }
    const poll = async () => {
      if (retryVersion.current !== null && retryDeadline.current === null) return;
      const version = ++pollVersion;
      clearTimeout(timer);
      const current = await load();
      if (disposed || version !== pollVersion) return;
      const status = jobRef.current?.status;
      // A disconnected POST may commit after several reads of the old terminal
      // version. Only a newer version or an explicit POST rejection resolves it.
      if (retryVersion.current === null && current && ['completed', 'partial', 'failed', 'cancelled'].includes(current.status) && !current.is_stopping) return;
      timer = setTimeout(poll, document.hidden ? 15000 : status?.startsWith('waiting_') ? 8000 : 3500);
    };
    const onVisibility = () => { if (!document.hidden) void poll(); };
    void poll();
    document.addEventListener('visibilitychange', onVisibility);
    return () => { disposed = true; clearTimeout(timer); clearTimeout(confirmationTimer); controllerRef.current?.abort(); document.removeEventListener('visibilitychange', onVisibility); };
  }, [load, revisionMode, pollingEpoch]);

  const cancel = async () => {
    setCancelling(true); setCancelError('');
    try { await cancelJob(id); await load(); }
    catch (err) { setCancelError(readableError(err)); }
    finally { setCancelling(false); }
  };
  const retry = async () => {
    if (retrying || retryVersion.current !== null) return;
    const submittedVersion = jobRef.current?.execution_version ?? 0;
    setRetrying(true);
    setRetryError('');
    try {
      const updated = await retryJob(id);
      jobRef.current = updated;
      setJob(updated);
      router.replace(`/jobs/${updated.id}`);
      setPollingEpoch((value) => value + 1);
    } catch (err) {
      setRetryError(readableError(err));
      if (err instanceof ApiError && err.status >= 400 && err.status < 500 && RETRY_REJECTION_CODES.has(err.code)) {
        setPollingEpoch((value) => value + 1);
        return;
      }
      retryVersion.current = submittedVersion;
      retryDeadline.current = Date.now() + RETRY_CONFIRMATION_MS;
      setReconcilingRetry(true);
      // The POST may have committed. Read the server again, and keep polling
      // through connection failures or an accepted pending/running attempt.
      setPollingEpoch((value) => value + 1);
    } finally {
      setRetrying(false);
    }
  };
  const resumeRetryCheck = () => {
    if (retryVersion.current === null) return;
    retryDeadline.current = Date.now() + RETRY_CONFIRMATION_MS;
    setRetryUnconfirmed(false);
    setReconcilingRetry(true);
    setPollingEpoch((value) => value + 1);
  };
  const reconnect = () => {
    if (retryVersion.current !== null) resumeRetryCheck();
    else setPollingEpoch((value) => value + 1);
  };
  const openRevision = () => { if (!job) return; setRevisionQuery((current) => current || job.query); setShowRevision(true); };
  const revise = async () => {
    if (!job || !revisionUserId || !revisionQuery.trim() || revisionQuery.trim() === job.query.trim()) return;
    setRevising(true);
    setRevisionError('');
    try {
      const user = await getCurrentUser();
      if (user.id !== revisionUserId) {
        const attempts = readRevisionAttempts(user.id, id);
        setRevisionUserId(user.id);
        setRevisionQuery(attempts[attempts.length - 1]?.query || job.query);
        setRevisionError('登录账号已变化，请确认当前账号的研究范围后再提交。');
        return;
      }
      const attempt = saveRevisionAttempt(user.id, id, revisionQuery.trim());
      const revised = await reviseJob(id, attempt);
      clearRevisionAttempt(user.id, id, attempt);
      router.replace(`/jobs/${revised.id}`);
    } catch (err) {
      setRevisionError(err instanceof RevisionStorageError ? err.message : readableError(err));
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
        {loading ? <LoadingState label="正在读取任务状态" /> : error ? <ErrorState description={error} action={<Button onClick={reconnect}>重新读取</Button>} /> : job && (
          <>
            <Link href="/history" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="h-4 w-4" aria-hidden="true" />返回任务列表</Link>
            <div className="mt-4 grid gap-5 border-b pb-7 sm:grid-cols-[1fr_auto] sm:items-start">
              <div className="min-w-0"><p className="eyebrow">研究任务 · {job.id.slice(0, 6)}</p><h1 className="break-content title-balance mt-3 font-display text-2xl font-semibold leading-relaxed sm:text-3xl">{job.query}</h1><div className="mt-4 flex flex-wrap items-center gap-3"><StatusBadge status={job.status} /><span className="font-mono text-xs tabular-nums text-muted-foreground">{job.progress}%</span><span className="text-xs text-muted-foreground">B站 · {job.analysis_mode === 'deep' ? '内容深度分析' : '标准分析'}</span></div></div>
              <div className="grid justify-items-start gap-2 sm:justify-items-end"><div className="flex flex-wrap gap-2">{['pending', 'running', 'waiting_user', 'waiting_candidate_confirmation'].includes(job.status) && <Button variant="secondary" className="text-destructive" size="sm" onClick={cancel} isLoading={cancelling}><Square className="h-3.5 w-3.5" aria-hidden="true" />取消任务</Button>}{job.can_retry && <Button size="sm" onClick={retry} isLoading={retrying || reconcilingRetry} disabled={retryUnconfirmed}><RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />重试任务</Button>}{job.can_revise && <Button variant="secondary" size="sm" onClick={openRevision}><PencilLine className="h-3.5 w-3.5" aria-hidden="true" />修改范围</Button>}</div>{retryError && <p className="max-w-sm text-sm text-destructive" role="alert">{retryError}{reconcilingRetry && ' 正在核对服务器上的任务状态，请稍候。'}</p>}{cancelError && <p className="max-w-sm text-sm text-destructive" role="alert">{cancelError}</p>}</div>
            </div>

            {retryUnconfirmed && <div className="mt-5 flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning/10 p-4 sm:flex-row sm:items-center" role="status"><p className="flex-1 text-sm leading-7">重试结果仍未确认。请稍后继续核对，避免重复提交。</p><Button variant="secondary" size="sm" onClick={resumeRetryCheck}><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />继续核对重试结果</Button></div>}
            {refreshError && <div className="mt-5 flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning/10 p-4 sm:flex-row sm:items-center" role="status"><p className="flex-1 text-sm leading-7">状态更新暂时中断，已保留当前内容与选择。{refreshError}</p><Button variant="secondary" size="sm" onClick={reconnect}><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />重新连接</Button></div>}
            <p className="mt-5 text-sm leading-7 text-muted-foreground" role="status">{job.is_stopping ? '正在停止并保存本次用量。完成后，这里会更新可用操作。' : job.status === 'waiting_user' ? '需要你补充下面的问题。提交后，研究会继续。' : job.status === 'waiting_candidate_confirmation' ? '样本已整理好，请决定哪些账号纳入分析。等待期间不会继续生成报告。' : job.status === 'pending' ? '任务已提交，正在等待后台接收。你可以离开，稍后从工作台继续查看。' : job.status === 'running' ? '正在依据公开样本处理研究。你可以离开页面，任务会继续执行。' : job.status === 'cancelled' ? `任务已取消，已产生的用量会保留。${job.can_retry ? '可以重试任务，或修改研究范围创建新任务。' : job.can_revise ? '可修改研究范围创建新任务。' : '请从工作台查看其他研究。'}` : job.status === 'failed' ? '这次研究暂未完成。请查看下方原因，再决定重试或修改范围。' : '研究记录已保存。'}</p>

            {job.revision_of_job_id && <p className="mt-4 text-sm text-muted-foreground">修订自 <Link href={`/jobs/${job.revision_of_job_id}`} className="font-mono font-semibold text-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{job.revision_of_job_id.slice(0, 8)}</Link></p>}

            {showRevision && job.can_revise && (
              <Card className="mt-6 p-5 sm:p-6">
                <p className="eyebrow">范围修订</p>
                <h2 className="mt-2 text-lg font-bold">创建修订任务</h2>
                <p className="mt-1 text-sm leading-7 text-muted-foreground">旧任务和回答会保留。修订将创建新任务，并占用 1 次本月额度。</p>
                <label htmlFor="revision-query" className="mt-4 block text-sm font-semibold">新的研究范围</label>
                <Textarea id="revision-query" className="mt-2 min-h-24" maxLength={2000} value={revisionQuery} disabled={!revisionUserId || revising} onChange={(event) => setRevisionQuery(event.target.value)} />
                {revisionError && <p className="mt-2 text-sm text-destructive" role="alert">{revisionError}</p>}
                {revisionError && !revisionUserId && <Button variant="secondary" size="sm" className="mt-2" onClick={() => setRevisionIdentityEpoch((value) => value + 1)}>重新读取修订草稿</Button>}
                <div className="mt-3 flex flex-wrap gap-2"><Button onClick={revise} isLoading={revising} disabled={!revisionUserId || !revisionQuery.trim() || revisionQuery.trim() === job.query.trim()}>创建修订任务</Button><Button variant="ghost" onClick={() => setShowRevision(false)} disabled={revising}>取消</Button></div>
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
              <CandidateConfirmation key={candidateSnapshot.snapshot_id} jobId={job.id} snapshot={candidateSnapshot} onSubmitted={async () => { await load(); }} />
            )}

            {clarificationHistory.length > 0 && (
              <section className="mt-7" aria-labelledby="clarification-history-title">
                <p className="eyebrow">已补充的范围</p>
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
              <div className="studio-hero px-5 py-6 sm:px-7"><div className="flex items-center justify-between gap-4"><div><h2 className="mt-2 font-display text-xl">这份研究的进展</h2></div><span className="font-mono text-2xl tabular-nums text-primary">{job.progress}%</span></div><div className="mt-5 h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="任务执行进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress}><div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${job.progress}%` }} /></div></div>
              <div className="p-5 sm:p-7"><JobProgress status={job.status} events={events} /></div>
            </Card>

            {job.error_message && <Card className="mt-4 border-destructive/30 p-5"><h2 className="mt-1 font-bold text-destructive">任务未完成</h2><p className="break-content mt-2 text-sm leading-6 text-muted-foreground">{job.error_message}</p><p className="mt-3 font-mono text-xs text-muted-foreground">{job.error_code}</p></Card>}
            <p className="mt-5 text-center text-xs leading-6 text-muted-foreground">任务状态已保存。{lastUpdated && `最近更新 ${lastUpdated.toLocaleTimeString('zh-CN')}`} · 同一任务重试不重复占用次数。</p>
          </>
        )}
      </div>
    </AppShell>
  );
}
