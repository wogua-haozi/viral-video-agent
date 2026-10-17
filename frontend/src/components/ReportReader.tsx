'use client';

import { useEffect, useMemo } from 'react';
import { ChevronDown } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { EvidenceCard, ReportClaim } from '@/components/product';
import { Card } from '@/components/ui';
import type { Claim, EvidenceItem } from '@/lib/api';
import { revealEvidence } from '@/lib/evidence';

type MarkdownNode = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: MarkdownNode[] };

// Link only IDs in the report's evidence set. Do not rewrite code blocks, URLs, or unknown IDs.
function citationPlugin(ids: Set<string>) {
  return () => (tree: MarkdownNode) => {
    const walk = (node: MarkdownNode) => {
      if (!node.children || ['a', 'code', 'pre'].includes(node.tagName || '')) return;
      node.children = node.children.flatMap((child) => {
        if (child.type !== 'text' || !child.value) { walk(child); return [child]; }
        const pieces: MarkdownNode[] = [];
        let offset = 0;
        for (const match of Array.from(child.value.matchAll(/\[(ev_[A-Za-z0-9_]+)\]/g))) {
          if (!ids.has(match[1])) continue;
          const start = match.index || 0;
          if (start > offset) pieces.push({ type: 'text', value: child.value.slice(offset, start) });
          pieces.push({ type: 'element', tagName: 'a', properties: { href: `#${match[1]}`, className: ['evidence-citation'] }, children: [{ type: 'text', value: match[0] }] });
          offset = start + match[0].length;
        }
        if (!pieces.length) return [child];
        if (offset < child.value.length) pieces.push({ type: 'text', value: child.value.slice(offset) });
        return pieces;
      });
    };
    walk(tree);
  };
}

export function ReportReader({ title, content, claims, evidence }: { title: string; content: string; claims: Claim[]; evidence: EvidenceItem[] }) {
  const plugin = useMemo(() => citationPlugin(new Set(evidence.map((item) => item.evidence_id))), [evidence]);
  useEffect(() => {
    let frame: number | undefined;
    try {
      const target = revealEvidence(decodeURIComponent(window.location.hash.slice(1)));
      // The report arrives asynchronously, after the browser's initial hash navigation.
      if (target) frame = requestAnimationFrame(() => target.scrollIntoView({ block: 'start' }));
    } catch { /* An invalid URL fragment does not affect reading. */ }
    return () => { if (frame !== undefined) cancelAnimationFrame(frame); };
  }, [evidence]);
  const jump = (id: string) => {
    const target = document.getElementById(id);
    if (target instanceof HTMLDetailsElement) target.open = true;
    revealEvidence(id);
  };

  return (
    <div className="min-w-0 space-y-5">
      <nav className="flex flex-wrap gap-x-5 gap-y-1 border-b pb-3 print:hidden" aria-label="报告阅读导航">
        {[['report-document', '阅读全文'], ['report-claims', `核对结论 · ${claims.length}`], ['report-evidence', `查看证据 · ${evidence.length}`]].map(([id, label]) => <a key={id} href={`#${id}`} onClick={() => jump(id)} className="inline-flex min-h-11 items-center rounded-sm text-xs font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{label}</a>)}
      </nav>
      <Card id="report-document" className="print-card scroll-mt-24 overflow-hidden p-0">
        <div className="print-header hidden border-b px-8 py-6 print:block"><p className="font-mono text-[10px] uppercase tracking-[.16em]">Viral Video Agent</p><h1 className="mt-2 font-display text-3xl">{title}</h1></div>
        <article className="report-prose p-5 sm:p-8 lg:p-10">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[plugin]} components={{
            a: ({ href, children, className, title: linkTitle }) => <a className={className} title={linkTitle} href={href} onClick={() => { if (href?.startsWith('#')) { try { jump(decodeURIComponent(href.slice(1))); } catch { /* Invalid fragment. */ } } }} {...(href?.startsWith('https://') || href?.startsWith('http://') ? { target: '_blank', rel: 'noreferrer' } : {})}>{children}</a>,
          }}>{content}</ReactMarkdown>
        </article>
      </Card>
      <p className="text-xs leading-6 text-muted-foreground print:hidden">正文已保留结论与来源附录。需要核对某一条时，可展开下面的详细视图，或点击正文中的证据编号。</p>
      <details id="report-claims" className="scroll-mt-24 rounded-xl border bg-card print:hidden">
        <summary className="reading-summary"><span><span className="block font-display text-xl">逐条核对结论</span><span className="mt-1 block text-xs font-normal text-muted-foreground">{claims.length} 条 · 数据观察、分析推断与行动建议</span></span><ChevronDown className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" /></summary>
        <div className="space-y-3 border-t p-4 sm:p-5"><p className="mb-4 text-xs leading-6 text-muted-foreground">分数表示模型自评信心，未经独立校准。请结合引用的实际样本核对判断。</p>{claims.length ? claims.map((claim, index) => <ReportClaim key={index} claim={claim} />) : <p className="text-sm text-muted-foreground">当前没有通过校验的结构化结论。</p>}</div>
      </details>
      <details id="report-evidence" className="scroll-mt-24 rounded-xl border bg-card print:hidden">
        <summary className="reading-summary"><span><span className="block font-display text-xl">回到样本与出处</span><span className="mt-1 block text-xs font-normal text-muted-foreground">{evidence.length} 条 · 实际字段、采集时间与转写片段</span></span><ChevronDown className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" /></summary>
        <div className="space-y-4 border-t p-4 sm:p-5">{evidence.length ? evidence.map((item) => <EvidenceCard key={item.evidence_id} evidence={item} />) : <p className="text-sm text-muted-foreground">当前没有可展示的来源证据。</p>}</div>
      </details>
    </div>
  );
}
