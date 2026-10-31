'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ArrowUpRight, Check, CheckCircle2, ChevronDown, ChevronRight, Clock3, Copy, ExternalLink, Link2 } from 'lucide-react';
import { Button, Card, Input, Modal, Select, StatusBadge, Textarea } from '@/components/ui';
import type { Claim, EvidenceItem, JobEvent, UsageSummary } from '@/lib/api';
import { createFeedback, createShareLink, readableError } from '@/lib/api';
import { cn } from '@/lib/utils';
import { revealEvidence, sourceDate, sourceUrl, timecode } from '@/lib/evidence';

const evidenceFields: [string, string][] = [
  ['author', '作者'], ['bvid', '视频编号'], ['view', '播放'], ['like', '点赞'],
  ['reply', '评论'], ['favorite', '收藏'], ['coin', '投币'], ['share', '分享'], ['duration', '时长'],
];

function fieldValue(value: unknown, key: string) {
  if (value === null || value === undefined || value === '') return '未提供';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '未提供';
    return key === 'duration' ? timecode(value) : value.toLocaleString('zh-CN');
  }
  return typeof value === 'string' || typeof value === 'boolean' ? String(value) : '未提供';
}

export function EvidenceCard({ evidence }: { evidence: EvidenceItem }) {
  const url = sourceUrl(evidence.source_url);
  const isTranscript = evidence.source_type === 'transcript';
  const fields = evidence.data_fields || {};
  const transcript = evidence.transcript_segment;
  const transcriptText = typeof transcript?.text === 'string' ? transcript.text : '';
  const segments = Array.isArray(transcript?.segments) ? transcript.segments.filter((item): item is { start?: number; end?: number; text: string } => Boolean(item && typeof item === 'object' && typeof item.text === 'string')) : [];
  // Platform describes the research scope; a Bilibili knowledge-base result is not a video sample.
  const isVideo = evidence.source_type === 'bilibili_video' || evidence.source_type === 'video';
  const sourceLabel = isTranscript ? '口播转写' : isVideo ? '视频样本' : evidence.source_type === 'knowledge_base' ? '知识参考' : evidence.source_type === 'trend_data' ? '趋势参考' : '工具来源';
  const publishDate = typeof fields.pubdate === 'number' && fields.pubdate > 0 ? new Date(fields.pubdate * 1000) : null;
  const publishedAt = typeof fields.published_at === 'string' ? fields.published_at : publishDate && !Number.isNaN(publishDate.getTime()) ? publishDate.toISOString() : null;
  return (
    <Card id={evidence.evidence_id} tabIndex={-1} className="print-avoid scroll-mt-24 overflow-hidden p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <div className="p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-2"><span className="max-w-full break-all rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">{evidence.evidence_id}</span><span className="text-xs text-muted-foreground">{sourceLabel}</span></div>
            <h3 className="break-content font-display text-lg font-semibold leading-7">{evidence.title || '未提供标题'}</h3>
            {evidence.summary && <p className="mt-3 text-pretty text-sm leading-7 text-muted-foreground">{evidence.summary}</p>}
          </div>
          {url && <a href={url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-full bg-muted/70 px-4 text-xs font-medium text-primary transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">回看来源<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a>}
        </div>
        {isVideo && <dl className="mt-6 grid grid-cols-2 gap-x-4 gap-y-5 rounded-xl bg-muted/50 p-4 sm:grid-cols-3">{evidenceFields.map(([key, label]) => <div key={key} className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-content mt-1.5 text-sm font-medium tabular-nums">{fieldValue(key === 'author' ? fields.author ?? fields.display_name : fields[key], key)}</dd></div>)}</dl>}
        {isTranscript && <details className="mt-4 rounded-lg border bg-muted/20"><summary className="reading-summary !min-h-11 !px-3 !py-3 text-sm">查看转写原文{segments.length > 0 ? ` · ${segments.length} 个片段` : ''}<ChevronDown className="h-4 w-4" aria-hidden="true" /></summary><div className="max-h-96 overflow-y-auto border-t p-4 text-sm leading-7" tabIndex={0} role="region" aria-label={`${evidence.title}的转写内容`}>{segments.length > 0 ? <ol className="space-y-4">{segments.map((segment, index) => <li key={index}><span className="font-mono text-xs text-primary">{timecode(segment.start)}{typeof segment.end === 'number' ? ` – ${timecode(segment.end)}` : ''}</span><p className="break-content mt-1">{segment.text}</p></li>)}</ol> : <p className="whitespace-pre-wrap break-content">{transcriptText || '未提供转写原文'}</p>}</div></details>}
        <dl className="mt-5 grid gap-3 border-t pt-4 text-xs leading-6">{isVideo && <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3"><dt className="text-muted-foreground">发布时间</dt><dd>{sourceDate(publishedAt)}</dd></div>}<div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3"><dt className="text-muted-foreground">采集时间</dt><dd>{sourceDate(evidence.fetched_at)}</dd></div><div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3"><dt className="text-muted-foreground">来源平台</dt><dd>{evidence.platform === 'bilibili' ? 'B 站' : evidence.platform || '未提供'}</dd></div><div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3"><dt className="text-muted-foreground">原始出处</dt><dd className="break-content">{url ? <a className="rounded-sm text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={url} target="_blank" rel="noreferrer">{url}</a> : '未提供'}</dd></div></dl>
      </div>
    </Card>
  );
}

const claimMeta = {
  observation: { label: '数据观察', style: 'bg-info/5 text-info' },
  inference: { label: '分析推断', style: 'bg-warning/10 text-warning-foreground dark:text-warning' },
  recommendation: { label: '行动建议', style: 'bg-success/5 text-success' },
} as const;

export function ReportClaim({ claim }: { claim: Claim }) {
  const meta = claimMeta[claim.claim_type] ?? claimMeta.inference;
  return (
    <article className="print-avoid rounded-2xl border border-border/60 bg-card p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <span className={cn('inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium', meta.style)}>{meta.label}</span>
        <span className="text-xs tabular-nums text-muted-foreground">模型自评 {Number.isFinite(claim.confidence) ? `${Math.round(claim.confidence * 100)}%` : '未提供'}</span>
      </div>
      <p className="text-pretty text-sm font-medium leading-7 text-foreground">{claim.claim}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {claim.evidence_ids.length ? claim.evidence_ids.map((id) => (
          <a key={id} href={`#${id}`} onClick={() => revealEvidence(id)} className="inline-flex min-h-11 max-w-full items-center gap-2 rounded-full bg-muted/70 px-3 py-2 font-mono text-xs text-primary transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Link2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /><span className="min-w-0 break-all">{id}</span>
          </a>
        )) : <span className="inline-flex items-center gap-2 text-xs font-medium text-warning-foreground dark:text-warning"><span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />该建议基于推断，不包含直接数值证据</span>}
      </div>
    </article>
  );
}

const phaseLabels: Record<string, string> = {
  queued: '排队中', clarification_needed: '需要补充研究范围', clarification_answered: '已收到范围补充', scope_confirmed: '研究范围已确认', collecting: '正在采集 B 站数据', retrieving: '正在检索知识库', waiting_candidate_confirmation: '等待确认候选账号', candidate_decisions_submitted: '候选确认已提交', validating: '正在验证 Evidence', analyzing: '正在分析', writing: '正在生成报告', persisting: '正在保存报告', completed: '报告已生成', partial: '已生成部分结果', failed: '任务失败', cancelled: '任务已取消',
};

export function JobProgress({ status, events }: { status: string; events: JobEvent[] }) {
  return (
    <div className="relative space-y-0">
      {events.map((event, index) => {
        const complete = event.progress >= 100;
        const failed = event.level === 'error';
        return (
          <div key={`${event.created_at}-${index}`} className="relative grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 pb-6 last:pb-0">
            {index < events.length - 1 && <span className="absolute left-[1.18rem] top-10 h-[calc(100%-2.5rem)] w-px bg-border/70" aria-hidden="true" />}
            <div className={cn('relative z-10 grid h-10 w-10 place-items-center rounded-full', failed ? 'bg-destructive/10 text-destructive' : complete ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground')}>
              {failed ? <span className="font-mono text-sm font-bold">!</span> : complete ? <Check className="h-4 w-4" aria-hidden="true" /> : <Clock3 className="h-4 w-4" aria-hidden="true" />}
            </div>
            <div className="min-w-0 pt-1">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold">{phaseLabels[event.event_type] || event.message}</p><span className="text-xs tabular-nums text-muted-foreground">{event.progress}%</span></div>
              <p className="break-content mt-1 text-sm leading-6 text-muted-foreground">{event.message}</p>
            </div>
          </div>
        );
      })}
      {!events.length && <div className="flex items-center gap-3 rounded-xl bg-muted/50 p-4 text-sm text-muted-foreground"><Clock3 className="h-4 w-4 shrink-0" aria-hidden="true" />{status === 'pending' ? '任务已创建，等待 Worker 接收。' : '正在读取任务事件。'}</div>}
    </div>
  );
}

export function UsageCard({ usage }: { usage: UsageSummary }) {
  const ratio = Math.min(100, Math.round((usage.jobs_used / Math.max(usage.jobs_limit, 1)) * 100));
  return (
    <Card className="p-5 sm:p-6">
      <p className="text-sm font-medium text-muted-foreground">本月已提交</p><p className="mt-3 flex flex-wrap items-baseline gap-2 text-3xl font-semibold tabular-nums">{usage.jobs_used}<span className="text-sm font-normal text-muted-foreground">/ {usage.jobs_limit} 次</span></p>
      <div className="mt-5 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="本月任务用量" aria-valuemin={0} aria-valuemax={usage.jobs_limit} aria-valuenow={usage.jobs_used}><div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${ratio}%` }} /></div>
      <p className="mt-4 text-xs leading-6 text-muted-foreground">本月已提交的任务次数。提交即占用额度；同一任务恢复或重试不重复计次，删除不返还。</p>
    </Card>
  );
}

export function FeedbackForm({ reportId }: { reportId: string }) {
  const [rating, setRating] = useState('5');
  const [useful, setUseful] = useState(true);
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    setLoading(true);
    setError('');
    try {
      await createFeedback(reportId, { rating: Number(rating), useful, reason, comment, adopted: null });
      setSent(true);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="p-5 sm:p-6" data-print-hide="true">
      <h2 className="mb-5 text-base font-semibold">这份报告有帮助吗？</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-semibold">是否有用<Select className="mt-2" value={useful ? 'yes' : 'no'} onChange={(event) => setUseful(event.target.value === 'yes')}><option value="yes">有用</option><option value="no">无用</option></Select></label>
        <label className="text-sm font-semibold">评分<Select className="mt-2" value={rating} onChange={(event) => setRating(event.target.value)}>{[5, 4, 3, 2, 1].map((value) => <option key={value} value={value}>{value} 分</option>)}</Select></label>
      </div>
      <label className="mt-4 block text-sm font-semibold">主要原因<Input className="mt-2" maxLength={100} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如：样本相关、建议具体、证据不足" /></label>
      <label className="mt-4 block text-sm font-semibold">补充说明 <span className="font-normal text-muted-foreground">（可选）</span><Textarea className="mt-2 min-h-24" maxLength={2000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="告诉我们哪些结论最有用，或哪里需要改进" /></label>
      {error && <p className="mt-3 text-sm font-medium text-destructive" role="alert">{error} 请稍后重试。</p>}
      <Button className="mt-4" onClick={submit} isLoading={loading} disabled={sent}>{sent ? '反馈已保存' : '提交反馈'}</Button>
      {sent && <p className="mt-3 text-sm text-success" role="status">反馈已保存，感谢你帮助完善这份研究。</p>}
    </Card>
  );
}

export function ShareDialog({ reportId }: { reportId: string }) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState('7');
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const create = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await createShareLink(reportId, Number(days));
      setUrl(`${window.location.origin}/share/${result.token}`);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true); setError('');
      setTimeout(() => setCopied(false), 1800);
    } catch { setError('无法访问剪贴板，请手动复制下面的链接。'); }
  };

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}><ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />分享</Button>
      <Modal open={open} title="创建只读分享链接" onClose={() => setOpen(false)}>
        <p className="text-pretty text-sm leading-6 text-muted-foreground">分享页展示报告与公开证据，隐藏账号、成本和内部日志。任何持有链接的人均可查看，到期后链接失效。</p>
        <label className="mt-5 block text-sm font-semibold">有效期<Select className="mt-2" value={days} onChange={(event) => setDays(event.target.value)} disabled={Boolean(url)}><option value="1">1 天后过期</option><option value="7">7 天后过期</option><option value="30">30 天后过期</option></Select></label>
        {error && <p className="mt-3 text-sm font-medium text-destructive" role="alert">{error} 请稍后重试。</p>}
        {url ? (
          <div className="mt-5">
            <label className="text-sm font-semibold">分享地址<Input className="mt-2 font-mono text-xs" readOnly value={url} /></label>
            <Button className="mt-3 w-full" onClick={copy}>{copied ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}{copied ? '已复制' : '复制链接'}</Button>
          </div>
        ) : <Button className="mt-5 w-full" onClick={create} isLoading={loading}>创建分享链接</Button>}
      </Modal>
    </>
  );
}

export function JobSummaryCard({ id, title, status, progress, createdAt }: { id: string; title: string; status: string; progress: number; createdAt: string }) {
  return (
    <Link href={`/jobs/${id}`} className="group block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
      <Card className="p-5 transition-colors group-hover:border-border group-hover:bg-muted/40 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 basis-40"><p className="break-content font-medium leading-7">{title}</p><p className="mt-2 text-xs tabular-nums text-muted-foreground">{new Date(createdAt).toLocaleString('zh-CN')}</p></div>
          <StatusBadge status={status} />
        </div>
        <div className="mt-5 flex items-center gap-3"><div className="h-1 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="任务进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><div className="h-full bg-primary" style={{ width: `${progress}%` }} /></div><span className="text-xs tabular-nums text-muted-foreground">{progress}%</span><ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" /></div>
      </Card>
    </Link>
  );
}
