'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, Copy, Download, ListChecks, PencilLine, Printer } from 'lucide-react';
import { useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { FeedbackForm, ShareDialog } from '@/components/product';
import { ReportReader } from '@/components/ReportReader';
import { Button, Card, ErrorState, LinkButton, LoadingState, StatusBadge, Toast } from '@/components/ui';
import { getReport, readableError, type Report } from '@/lib/api';

type TraceAgent = { agent: string; duration_s: number; llm_calls: number };

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true; setReport(null); setError('');
    getReport(id).then((value) => { if (active) setReport(value); }).catch((err) => { if (active) setError(readableError(err)); });
    return () => { active = false; };
  }, [id, reload]);

  const exportMarkdown = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([report.content], { type: 'text/markdown;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${report.title}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.content);
      setCopied(true); setCopyError('');
      setTimeout(() => setCopied(false), 1800);
    } catch { setCopyError('无法访问剪贴板。你可以下载 Markdown，或选中正文手动复制。'); }
  };

  if (error) return <AppShell><ErrorState description={error} action={<Button onClick={() => setReload((value) => value + 1)}>重新读取</Button>} /></AppShell>;
  if (!report) return <AppShell><LoadingState label="正在加载报告" /></AppShell>;
  const trace = report.model_info?.trace as { total_duration_s?: number; total_llm_calls?: number; agents?: TraceAgent[] } | undefined;

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl">
        <div className="mb-7 border-b pb-7 print:hidden">
          <Link href="/history" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="h-4 w-4" aria-hidden="true" />返回历史</Link>
          <div className="mt-3 flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-3"><StatusBadge status={report.status} /><span className="font-mono text-[11px] tabular-nums text-muted-foreground">{new Date(report.created_at).toLocaleString('zh-CN')}</span></div><p className="eyebrow mt-4">Research note / {report.id.slice(0, 6)}</p><h1 className="break-content title-balance mt-3 max-w-4xl font-display text-3xl font-semibold leading-snug sm:text-4xl">{report.title}</h1></div>
            <div className="flex flex-wrap gap-2"><LinkButton href={`/jobs/${report.job_id}?revise=1`} variant="secondary" size="sm"><PencilLine className="h-3.5 w-3.5" aria-hidden="true" />修改范围</LinkButton><Button variant="secondary" size="sm" onClick={copy}><Copy className="h-3.5 w-3.5" aria-hidden="true" />复制</Button><Button variant="secondary" size="sm" onClick={exportMarkdown}><Download className="h-3.5 w-3.5" aria-hidden="true" />Markdown</Button><Button variant="secondary" size="sm" onClick={() => window.print()}><Printer className="h-3.5 w-3.5" aria-hidden="true" />PDF</Button><ShareDialog reportId={report.id} /></div>
          </div>
        </div>

        {copyError && <p className="mb-4 text-sm text-destructive" role="alert">{copyError}</p>}
        {report.status === 'partial' && <div className="mb-5 flex gap-3 border border-warning/40 bg-warning/10 p-4 text-sm leading-6 text-foreground" role="status"><span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-warning" aria-hidden="true" /><p><strong>部分结果：</strong>这次研究保留了可用结果。请先阅读报告中的局限说明，再决定哪些建议值得验证。</p></div>}

        <div className="grid gap-7 xl:grid-cols-[minmax(0,1fr)_19rem]">
          <div className="min-w-0 space-y-9">
            <ReportReader title={report.title} content={report.content} claims={report.structured_claims} evidence={report.evidence} />
            <FeedbackForm key={report.id} reportId={report.id} />
          </div>

          <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
            <Card className="p-5"><div className="flex items-center gap-2"><ListChecks className="h-4 w-4 text-primary" aria-hidden="true" /><p className="eyebrow">Appendix</p></div><h2 className="mt-2 font-bold">本次研究</h2><dl className="mt-4 divide-y text-sm"><div className="flex justify-between gap-3 py-3"><dt className="text-muted-foreground">公开来源</dt><dd className="font-mono font-semibold">{report.evidence.length} 条</dd></div><div className="flex justify-between gap-3 py-3"><dt className="text-muted-foreground">结构化结论</dt><dd className="font-mono font-semibold">{report.structured_claims.length} 条</dd></div><div className="flex justify-between gap-3 py-3"><dt className="text-muted-foreground">平台</dt><dd className="font-semibold">B站</dd></div></dl></Card>
            {report.usage && <Card className="p-5 print:hidden"><p className="eyebrow">Usage</p><h2 className="mt-2 font-bold">研究用量</h2><dl className="mt-4 divide-y text-sm"><div className="flex justify-between gap-3 py-3"><dt className="text-muted-foreground">Token</dt><dd className="break-content font-mono font-semibold">{report.usage.input_tokens + report.usage.output_tokens}</dd></div><div className="flex justify-between gap-3 py-3"><dt className="text-muted-foreground">估算成本</dt><dd className="font-mono font-semibold">${report.usage.estimated_cost.toFixed(4)}</dd></div><div className="flex justify-between gap-3 py-3"><dt className="text-muted-foreground">ASR</dt><dd className="font-mono font-semibold">{report.usage.asr_seconds}s</dd></div></dl></Card>}
            <Card className="p-5 print:hidden"><details><summary className="min-h-11 cursor-pointer list-none font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Agent 执行轨迹</summary><p className="mt-2 text-xs leading-5 text-muted-foreground">仅账号所有者可见，不会进入公开分享。</p>{trace ? <div className="mt-4 space-y-2 text-xs"><div className="flex justify-between border-b pb-2"><span>总耗时</span><span className="font-mono">{trace.total_duration_s || 0}s</span></div><div className="flex justify-between border-b pb-2"><span>LLM 调用</span><span className="font-mono">{trace.total_llm_calls || 0} 次</span></div>{trace.agents?.map((agent) => <div key={agent.agent} className="rounded-lg border bg-muted/60 p-3"><div className="flex justify-between gap-2"><span className="break-content font-semibold">{agent.agent}</span><span className="font-mono">{agent.duration_s}s</span></div><div className="mt-1 text-muted-foreground">LLM {agent.llm_calls} 次</div></div>)}</div> : <p className="mt-3 text-xs text-muted-foreground">暂无执行轨迹。</p>}</details></Card>
          </aside>
        </div>
        {copied && <Toast message="报告已复制" />}
      </div>
    </AppShell>
  );
}
