'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { CheckCircle2, FileSearch, Info, Sparkles } from 'lucide-react';
import { Suspense, useEffect, useRef, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Button, Card, Select, Skeleton, Textarea } from '@/components/ui';
import { createJob, getCapabilities, readableError, type AnalysisMode } from '@/lib/api';

const queryByTemplate: Record<string, string> = {
  'B站赛道爆款分析': '分析B站「」赛道近期代表视频的内容特征、标题结构和可执行选题建议',
  '竞品账号内容拆解': '拆解B站竞品账号「」的代表内容、标题方式和可复用策略',
  '热门标题结构分析': '分析B站「」主题热门视频的标题结构、承诺方式和受众表达',
  '选题方向分析': '为B站「」赛道寻找值得验证的选题方向，并给出真实样本依据',
  '内容脚本深度分析': '分析B站「」主题代表视频的开头、口播和脚本结构',
};

const promptHints = [
  { label: 'AI 编程 · 标题与开场', query: '分析B站近30天AI编程教程的代表视频，重点看标题钩子与开场表达，给出有样本依据的选题建议。' },
  { label: '相机测评 · 竞品定位', query: '分析B站近90天持续发布相机测评的账号，排除旅行日志，重点比较选题、标题和内容定位。' },
  { label: '美食教程 · 内容结构', query: '分析B站近30天家常菜教程，关注步骤展示、时长与标题表达，寻找适合新账号尝试的内容方向。' },
];

const attemptStorageKey = 'viral-video:new-job-attempt';

function NewJobForm() {
  const params = useSearchParams();
  const router = useRouter();
  const template = params.get('template') || '';
  const [query, setQuery] = useState(queryByTemplate[template] || '');
  const [mode, setMode] = useState<AnalysisMode>('standard');
  const [deepAvailable, setDeepAvailable] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const submittingRef = useRef(false);
  const validQuery = query.trim().length >= 2 && query.trim().length <= 2000;

  useEffect(() => {
    if (template) return;
    try {
      const saved = JSON.parse(sessionStorage.getItem(attemptStorageKey) || 'null');
      const draft = saved && typeof saved.fingerprint === 'string' ? JSON.parse(saved.fingerprint) : null;
      if (typeof saved?.key === 'string' && typeof draft?.query === 'string'
        && draft.query.trim().length >= 2 && draft.query.length <= 2000
        && ['standard', 'deep'].includes(draft.analysis_mode)) {
        attempt.current = saved;
        setQuery(draft.query);
        setMode(draft.analysis_mode);
      }
    } catch { /* An unavailable or invalid draft must not block a new inquiry. */ }
  }, [template]);

  useEffect(() => {
    getCapabilities()
      .then((data) => setDeepAvailable(Boolean(data.items.find((item) => item.name === 'get_transcript' && item.enabled))))
      .catch(() => setDeepAvailable(false));
  }, []);

  const submit = async () => {
    if (!validQuery || submittingRef.current) return;
    submittingRef.current = true;
    setLoading(true);
    setError('');
    const fingerprint = JSON.stringify({ query: query.trim(), analysis_mode: mode });
    // Persist an unresolved submission per tab: a lost response must not create a new job.
    if (!attempt.current) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(attemptStorageKey) || 'null');
        if (saved && typeof saved.key === 'string' && typeof saved.fingerprint === 'string') attempt.current = saved;
      } catch { /* Storage may be unavailable; the in-memory identity still handles retries. */ }
    }
    if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID() };
    try { sessionStorage.setItem(attemptStorageKey, JSON.stringify(attempt.current)); } catch { /* Optional persistence. */ }
    try {
      const job = await createJob({ query: query.trim(), analysis_mode: mode, idempotency_key: attempt.current.key });
      try { sessionStorage.removeItem(attemptStorageKey); } catch { /* Optional persistence. */ }
      attempt.current = null;
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(readableError(err));
      setLoading(false);
      submittingRef.current = false;
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl">
        <div className="grid gap-5 border-b pb-7 xl:grid-cols-[1fr_auto] xl:items-end">
          <div><p className="eyebrow">A new inquiry</p><h1 className="title-balance mt-3 font-display text-3xl font-semibold leading-snug sm:text-4xl">这次，你想看清什么？</h1><p className="mt-4 max-w-2xl text-pretty text-sm leading-7 text-muted-foreground">写下一个具体的问题。我们会从 B 站公开样本中整理线索，保留每条结论的出处。</p></div>
          <div className="inline-flex items-center gap-2 text-xs font-semibold text-success"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />B 站公开样本</div>
        </div>

        <div className="mt-7 grid gap-6 xl:grid-cols-[minmax(0,1fr)_18rem]">
          <Card className="p-5 sm:p-7">
            <label htmlFor="analysis-query" className="font-display text-xl font-semibold">你的研究问题 <span className="text-destructive" aria-hidden="true">*</span></label>
            <p id="analysis-query-hint" className="mt-2 text-xs leading-6 text-muted-foreground">至少 2 个字，最多 2000 字。写明研究对象、时间范围和你想解决的问题。日期要求须以报告中实际核验的范围为准。</p>
            <Textarea id="analysis-query" value={query} onChange={(event) => { setQuery(event.target.value); setError(''); }} maxLength={2000} minLength={2} required className="mt-4 min-h-48" placeholder="例如：分析 B 站近 30 天的 AI 编程教程，重点看标题与开场，给我 3 个可以尝试的选题方向。" aria-describedby="analysis-query-hint analysis-query-count" />
            <p id="analysis-query-count" className="mt-2 text-right font-mono text-[11px] text-muted-foreground">{query.length} / 2000</p>

            <div className="mt-4 flex flex-wrap gap-2" aria-label="需求示例">
              {promptHints.map((item) => <Button key={item.label} variant="ghost" size="sm" className="border text-xs" onClick={() => { setQuery(item.query); setError(''); }}>{item.label}</Button>)}
            </div>

            <div className="mt-6 grid gap-5 border-t pt-6 sm:grid-cols-2">
              <label className="text-sm font-semibold">研究平台<Select className="mt-2" value="bilibili" disabled><option value="bilibili">B 站</option></Select><span className="mt-2 block text-xs font-normal text-muted-foreground">仅采集公开可访问的样本。</span></label>
              <label className="text-sm font-semibold">分析深度<Select className="mt-2" value={mode} onChange={(event) => setMode(event.target.value as AnalysisMode)}><option value="standard">标准 · 标题、账号与互动数据</option><option value="deep" disabled={!deepAvailable}>{deepAvailable ? '深入 · 增加代表视频口播转写' : '深入 · 转写能力暂不可用'}</option></Select><span className="mt-2 block text-xs font-normal text-muted-foreground">深入分析适合研究开场、口播与脚本。</span></label>
            </div>

            <div className="mt-6 flex gap-3 rounded-lg border bg-muted/40 p-4 text-sm leading-7 text-muted-foreground"><Info className="mt-1 h-4 w-4 shrink-0 text-primary" aria-hidden="true" /><div><p>{mode === 'deep' ? '将尝试转写最多 5 个代表视频，会增加耗时与用量。转写失败时，报告会说明降级情况。' : '提交后可离开页面，任务会继续处理。若需要你补充范围或确认账号，请从工作台返回继续。'}</p><p className="mt-2 text-xs">提交时占用 1 次本月额度。同一任务恢复或重试不重复计次，删除任务不返还额度。</p></div></div>
            {error && <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm leading-7 text-destructive" role="alert"><p>{error}</p><p className="mt-1 text-xs">需求与深度不变时，重试会复用这次提交，避免网络中断造成重复任务。</p></div>}
            <div className="mt-6 flex justify-end"><Button size="lg" onClick={submit} disabled={!validQuery} isLoading={loading}>{error ? '重试这次提交' : '开始研究'}<FileSearch className="h-4 w-4" aria-hidden="true" /></Button></div>
          </Card>

          <aside className="space-y-4">
            <Card className="p-5"><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-lg border bg-accent/10 text-accent"><Sparkles className="h-4 w-4" aria-hidden="true" /></div><div><p className="eyebrow text-accent">Prompt guide</p><h2 className="mt-1 font-bold">写得更具体</h2></div></div><ol className="mt-5 space-y-4 text-sm text-muted-foreground">{['指定赛道、账号或主题', '说明重点看标题、内容或互动', '写清希望得到的行动建议'].map((item, index) => <li key={item} className="grid grid-cols-[2rem_1fr] gap-2"><span className="font-mono text-xs font-bold text-primary">0{index + 1}</span><span>{item}</span></li>)}</ol></Card>
            <section className="studio-hero rounded-xl border p-5"><p className="eyebrow">What you will receive</p><h2 className="mt-3 font-display text-xl">一份可回看的研究手记</h2><p className="mt-3 text-sm leading-7 text-[#c9b99f]">研究正文、观察与建议、实际样本数据、来源链接，以及本次研究的局限。</p></section>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

export default function NewJobPage() {
  return (
    <Suspense fallback={<AppShell><div className="mx-auto max-w-5xl space-y-4"><Skeleton className="h-24" /><Skeleton className="h-[34rem]" /></div></AppShell>}>
      <NewJobForm />
    </Suspense>
  );
}
