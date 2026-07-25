'use client';

import { ExternalLink, FileSearch, ShieldCheck } from 'lucide-react';
import { useRef, useState } from 'react';
import { Button, Card, Textarea } from '@/components/ui';
import { readableError, submitCandidateDecisions, type CandidateDecision, type CandidateSnapshot } from '@/lib/api';
import { cn } from '@/lib/utils';

const options: { value: Exclude<CandidateDecision, 'undecided'>; label: string; description: string }[] = [
  { value: 'confirmed', label: '纳入分析', description: '报告会使用该账号对应的原始 Evidence。' },
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

  const missing = snapshot.candidates.filter((item) => !decisions[item.candidate_id] || decisions[item.candidate_id] === 'undecided');
  const confirmedCount = snapshot.candidates.filter((item) => decisions[item.candidate_id] === 'confirmed').length;

  const submit = async () => {
    setAttempted(true);
    setSubmitError('');
    if (missing.length || confirmedCount < 1) return;
    if (!requestId.current) requestId.current = crypto.randomUUID();
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
      await onSubmitted();
    } catch (error) {
      setSubmitError(readableError(error));
    } finally {
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
              <h2 id="candidate-confirmation-title" className="mt-2 text-xl font-black">确认本次分析账号</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">候选来自本次公开 Evidence 快照。每项都要明确选择，且至少纳入一个账号。</p>
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
              <fieldset key={candidate.candidate_id} className={cn('min-w-0 rounded-xl border bg-card p-4 sm:p-5', hasError && 'border-destructive/60')} aria-describedby={hasError ? errorId : undefined}>
                <legend className="max-w-full px-1 text-base font-bold">
                  <span className="mr-2 font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, '0')}</span>
                  {candidate.display_name || '未提供账号名称'}
                </legend>
                <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
                  <a href={candidate.profile_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">账号主页<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a>
                  <span>{candidate.matched_video_count} 条匹配样本</span>
                  <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-success" aria-hidden="true" />稳定 MID 身份</span>
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,.9fr)]">
                  <div className="min-w-0">
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
                    <label htmlFor={`candidate-reason-${candidate.candidate_id}`} className="mt-3 block text-xs font-semibold text-muted-foreground">简短原因 <span className="font-normal">（可选，最多 200 字）</span></label>
                    <Textarea id={`candidate-reason-${candidate.candidate_id}`} className="mt-2 min-h-20" maxLength={200} value={reasons[candidate.candidate_id] || ''} onChange={(event) => setReasons((current) => ({ ...current, [candidate.candidate_id]: event.target.value }))} placeholder="例如：内容长期匹配本次范围" />
                    {hasError && <p id={errorId} className="mt-2 text-sm font-medium text-destructive" role="alert">请为该候选明确选择一项。</p>}
                  </div>
                </div>
              </fieldset>
            );
          })}

          <div className="flex flex-col gap-3 border-t pt-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-muted-foreground"><span className="font-semibold text-foreground">已纳入 {confirmedCount} 个</span> · 已选择 {snapshot.candidates.length - missing.length}/{snapshot.candidates.length}</div>
            <Button onClick={submit} isLoading={submitting} disabled={!snapshot.can_submit}>提交确认并生成报告</Button>
          </div>
          {attempted && !missing.length && confirmedCount < 1 && <p className="text-sm font-medium text-destructive sm:text-right" role="alert">至少选择一个“纳入分析”。</p>}
          {submitError && <p className="text-sm font-medium text-destructive sm:text-right" role="alert">{submitError}</p>}
          <p className="text-xs leading-5 text-muted-foreground">提交后会恢复同一个任务，只运行 Analyst/Writer；不会重新搜索或转写。</p>
        </div>
      </Card>
    </section>
  );
}
