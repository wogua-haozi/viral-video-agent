'use client';

import { ChevronDown, ExternalLink, FileSearch, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button, Card, Textarea } from '@/components/ui';
import { readableError, submitCandidateDecisions, type CandidateDecision, type CandidateSnapshot } from '@/lib/api';
import { cn } from '@/lib/utils';

const options: { value: Exclude<CandidateDecision, 'undecided'>; label: string; description: string }[] = [
  { value: 'confirmed', label: '纳入分析', description: '使用该账号的公开样本形成结论。' },
  { value: 'excluded', label: '排除', description: '该账号不会进入正常竞品结论。' },
  { value: 'uncertain', label: '不确定', description: '只会出现在未纳入或待确认范围中。' },
];

export function CandidateConfirmation({ jobId, snapshot, onSubmitted }: { jobId: string; snapshot: CandidateSnapshot; onSubmitted: () => Promise<void> }) {
  const [decisions, setDecisions] = useState<Record<string, CandidateDecision>>(() => Object.fromEntries(snapshot.candidates.map((item) => [item.candidate_id, item.decision])));
  const [reasons, setReasons] = useState<Record<string, string>>(() => Object.fromEntries(snapshot.candidates.map((item) => [item.candidate_id, item.reason || ''])));
  const [attempted, setAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const requestId = useRef('');
  const requestFingerprint = useRef('');
  const submittingRef = useRef(false);
  const fields = useRef<Record<string, HTMLFieldSetElement | null>>({});
  const [draftReady, setDraftReady] = useState(false);
  const draftKey = `viral-video:candidates:${jobId}:${snapshot.snapshot_id}`;

  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey) || 'null');
      if (saved) {
        setDecisions((current) => Object.fromEntries(snapshot.candidates.map((item) => [item.candidate_id, ['confirmed', 'excluded', 'uncertain'].includes(saved.decisions?.[item.candidate_id]) ? saved.decisions[item.candidate_id] : current[item.candidate_id]])));
        setReasons((current) => Object.fromEntries(snapshot.candidates.map((item) => [item.candidate_id, typeof saved.reasons?.[item.candidate_id] === 'string' ? saved.reasons[item.candidate_id].slice(0, 200) : current[item.candidate_id]])));
      }
    } catch { /* Draft storage is optional; keep the current form usable. */ }
    setDraftReady(true);
    // A new snapshot remounts this component; polling must not reinitialize its draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  useEffect(() => {
    if (!draftReady) return;
    try { sessionStorage.setItem(draftKey, JSON.stringify({ decisions, reasons })); } catch { /* Optional persistence. */ }
  }, [draftKey, draftReady, decisions, reasons]);

  const missing = snapshot.candidates.filter((item) => !decisions[item.candidate_id] || decisions[item.candidate_id] === 'undecided');
  const confirmedCount = snapshot.candidates.filter((item) => decisions[item.candidate_id] === 'confirmed').length;

  const submit = async () => {
    if (submittingRef.current) return;
    setAttempted(true);
    setSubmitError('');
    if (missing.length || confirmedCount < 1) {
      const candidate = missing[0] || snapshot.candidates[0];
      fields.current[candidate?.candidate_id]?.querySelector('input')?.focus();
      return;
    }
    const fingerprint = JSON.stringify({ decisions, reasons });
    if (!requestId.current || requestFingerprint.current !== fingerprint) {
      requestId.current = crypto.randomUUID(); requestFingerprint.current = fingerprint;
    }
    submittingRef.current = true;
    setSubmitting(true);
    try {
      await submitCandidateDecisions(jobId, {
        request_id: requestId.current,
        snapshot_id: snapshot.snapshot_id,
        decisions: snapshot.candidates.map((item) => ({
          candidate_id: item.candidate_id,
          decision: decisions[item.candidate_id] as Exclude<CandidateDecision, 'undecided'>,
          ...(reasons[item.candidate_id]?.trim() ? { reason: reasons[item.candidate_id].trim() } : {}),
        })),
      });
      try { sessionStorage.removeItem(draftKey); } catch { /* Optional persistence. */ }
      await onSubmitted();
    } catch (error) {
      setSubmitError(readableError(error));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <section className="mt-6" aria-labelledby="candidate-confirmation-title">
      <Card className="overflow-hidden p-0">
        <div className="border-b bg-muted/45 px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="eyebrow">Candidate confirmation</p>
              <h2 id="candidate-confirmation-title" className="mt-2 font-display text-2xl font-semibold">哪些账号值得放在一起研究？</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">以下候选来自这次采集的公开样本。请逐项选择，至少纳入一个；不确定的账号不会进入正常竞品结论。</p>
            </div>
            <div className="shrink-0 rounded-lg border bg-background px-3 py-2 text-xs text-muted-foreground">
              <span className="font-mono font-semibold text-foreground">{snapshot.candidates.length}/{snapshot.max_candidates}</span> 个候选
            </div>
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="text-xs text-muted-foreground">研究主题</dt><dd className="mt-1 font-semibold">{snapshot.topic_spec.topic}</dd></div>
            <div><dt className="text-xs text-muted-foreground">内容范围</dt><dd className="mt-1 font-semibold">{snapshot.topic_spec.target_content.join('、') || '以已确认 TopicSpec 为准'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">时间范围</dt><dd className="mt-1 font-semibold">{snapshot.topic_spec.time_window_days ? `近 ${snapshot.topic_spec.time_window_days} 天` : '未限定'}</dd></div>
          </dl>
        </div>

        <div className="grid gap-4 p-4 sm:p-6">
          {snapshot.candidates.map((candidate, index) => {
            const hasError = attempted && (!decisions[candidate.candidate_id] || decisions[candidate.candidate_id] === 'undecided');
            const errorId = `candidate-error-${candidate.candidate_id}`;
            return (
              <fieldset key={candidate.candidate_id} ref={(element) => { fields.current[candidate.candidate_id] = element; }} disabled={submitting} className={cn('min-w-0 rounded-xl border bg-card p-4 sm:p-5', hasError && 'border-destructive/60')} aria-describedby={hasError ? errorId : undefined}>
                <legend className="max-w-full px-1 text-base font-bold">
                  <span className="mr-2 font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, '0')}</span>
                  {candidate.display_name || '未提供账号名称'}
                </legend>
                <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
                  <a href={candidate.profile_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">账号主页<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a>
                  <span>{candidate.matched_video_count} 条匹配样本</span>
                  <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-success" aria-hidden="true" />账号标识可追溯</span>
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,.9fr)]">
                  <div className="min-w-0">
                    {candidate.why_surfaced.length > 0 && <p className="mb-3 text-xs leading-6 text-muted-foreground">入选线索：{candidate.why_surfaced.join('；')}</p>}
                    <p className="text-xs font-semibold uppercase tracking-[.12em] text-muted-foreground">真实视频样本</p>
                    <ul className="mt-2 space-y-2 text-sm leading-6">
                      {candidate.sample_titles.slice(0, 3).map((title) => <li key={title} className="break-content rounded-lg bg-muted/45 px-3 py-2">{title}</li>)}
                    </ul>
                    {candidate.evidence_links.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{candidate.evidence_links.map((item) => <a key={item.evidence_id} href={item.source_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border px-3 text-xs font-semibold text-primary transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><FileSearch className="h-3.5 w-3.5" aria-hidden="true" />Evidence {item.evidence_id.slice(-6)}</a>)}</div>}
                  </div>

                  <div className="min-w-0">
                    <div className="grid gap-2" role="radiogroup" aria-label={`${candidate.display_name || '候选账号'}的处理决定`}>
                      {options.map((option) => (
                        <label key={option.value} className={cn('flex min-h-14 cursor-pointer gap-3 rounded-lg border p-3 transition-colors hover:border-primary/40', decisions[candidate.candidate_id] === option.value && 'border-primary bg-primary/5')}>
                          <input type="radio" name={`candidate-${candidate.candidate_id}`} value={option.value} checked={decisions[candidate.candidate_id] === option.value} onChange={() => setDecisions((current) => ({ ...current, [candidate.candidate_id]: option.value }))} className="mt-1 h-4 w-4 shrink-0 accent-primary" />
                          <span><strong className="block text-sm">{option.label}</strong><span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{option.description}</span></span>
                        </label>
                      ))}
                    </div>
                    <details className="mt-3 rounded-lg border" open={reasons[candidate.candidate_id] ? true : undefined}><summary className="reading-summary !min-h-11 !px-3 !py-2 text-xs text-muted-foreground">{reasons[candidate.candidate_id] ? '已填写原因' : '添加简短原因（可选）'}<ChevronDown className="h-3.5 w-3.5" aria-hidden="true" /></summary><div className="px-3 pb-3"><label htmlFor={`candidate-reason-${candidate.candidate_id}`} className="text-xs text-muted-foreground">最多 200 字</label><Textarea id={`candidate-reason-${candidate.candidate_id}`} className="mt-2 min-h-20" maxLength={200} value={reasons[candidate.candidate_id] || ''} onChange={(event) => setReasons((current) => ({ ...current, [candidate.candidate_id]: event.target.value }))} placeholder="例如：内容长期匹配本次范围" /></div></details>
                    {hasError && <p id={errorId} className="mt-2 text-sm font-medium text-destructive" role="alert">请为该候选明确选择一项。</p>}
                  </div>
                </div>
              </fieldset>
            );
          })}

          <div className="sticky bottom-0 z-10 flex flex-col gap-3 border-t bg-card/95 py-4 backdrop-blur-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-muted-foreground"><span className="font-semibold text-foreground">已纳入 {confirmedCount} 个</span> · 已选择 {snapshot.candidates.length - missing.length}/{snapshot.candidates.length}</div>
            <div className="flex flex-wrap gap-2">{missing.length > 0 && <Button variant="ghost" size="sm" disabled={submitting} onClick={() => fields.current[missing[0].candidate_id]?.querySelector('input')?.focus()}>前往未确认项</Button>}<Button onClick={submit} isLoading={submitting} disabled={!snapshot.can_submit}>确认并继续</Button></div>
          </div>
          {attempted && !missing.length && confirmedCount < 1 && <p className="text-sm font-medium text-destructive sm:text-right" role="alert">至少选择一个“纳入分析”。</p>}
          {submitError && <p className="text-sm font-medium text-destructive sm:text-right" role="alert">{submitError}</p>}
          <p className="text-xs leading-6 text-muted-foreground">将基于已有样本继续生成报告，不重复搜索或转写，也不重复占用任务次数。</p>
        </div>
      </Card>
    </section>
  );
}
