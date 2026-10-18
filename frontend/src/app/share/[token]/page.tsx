'use client';

import { useParams } from 'next/navigation';
import { Eye, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ReportReader } from '@/components/ReportReader';
import { Card, ErrorState, LoadingState, StatusBadge } from '@/components/ui';
import { getSharedReport, readableError, type Report } from '@/lib/api';

export default function SharedReportPage() {
  const { token } = useParams<{ token: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');

  useEffect(() => { getSharedReport(token).then(setReport).catch((err) => setError(readableError(err))); }, [token]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-12 lg:px-8">
      {error ? <ErrorState title="分享链接不可用" description={error} /> : !report ? <LoadingState label="正在加载只读报告" /> : (
        <>
          <div className="grid gap-6 border-b pb-7 lg:grid-cols-[1fr_auto] lg:items-end">
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-3"><StatusBadge status={report.status} /><span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground"><Eye className="h-3.5 w-3.5" aria-hidden="true" />只读分享</span></div><h1 className="break-content title-balance mt-3 font-display text-3xl font-semibold leading-snug sm:text-4xl">{report.title}</h1><p className="mt-3 max-w-3xl text-pretty text-sm leading-6 text-muted-foreground">一份关于 B 站公开内容的研究手记。你可以阅读结论、查看样本，并回到原始出处。</p></div>
            <div className="inline-flex items-center gap-2 text-xs font-semibold text-success"><ShieldCheck className="h-4 w-4" aria-hidden="true" />公开只读版本</div>
          </div>

          <div className="mt-7 grid gap-7 xl:grid-cols-[minmax(0,1fr)_17rem]">
            <div className="min-w-0 space-y-9">
              <ReportReader title={report.title} content={report.content} claims={report.structured_claims} evidence={report.evidence} />
            </div>
            <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start"><Card className="p-5"><p className="eyebrow">Public boundary</p><h2 className="mt-2 font-bold">分享页不包含</h2><ul className="mt-4 space-y-3 text-sm text-muted-foreground"><li>用户邮箱与身份信息</li><li>Token、成本与用量</li><li>Agent 内部执行轨迹</li><li>Worker 错误详情</li></ul></Card><Card className="p-5"><p className="eyebrow">Platform</p><p className="mt-3 text-sm leading-6 text-muted-foreground">本报告只围绕公开可访问的 B 站样本，不代表全平台或行业总体。</p></Card></aside>
          </div>
        </>
      )}
    </main>
  );
}
