'use client';

import { CalendarDays, LogOut, Mail, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { UsageCard } from '@/components/product';
import { Button, Card, ErrorState, LoadingState } from '@/components/ui';
import { getCurrentUser, getUsage, logout, readableError, type User, type UsageSummary } from '@/lib/api';

export default function SettingsPage() {
  const [user, setUser] = useState<User | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [error, setError] = useState('');
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    Promise.all([getCurrentUser(), getUsage()])
      .then(([currentUser, value]) => { setUser(currentUser); setUsage(value); })
      .catch((err) => setError(readableError(err)));
  }, []);

  const signOut = async () => {
    setSigningOut(true);
    try {
      await logout();
      window.location.href = '/';
    } catch (err) {
      setError(readableError(err));
      setSigningOut(false);
    }
  };

  return (
    <AppShell>
      <div className="mb-7 border-b pb-7"><p className="eyebrow">Account / 04</p><h1 className="title-balance mt-2 font-display text-3xl font-semibold leading-snug sm:text-4xl">账号与用量</h1><p className="mt-2 text-sm text-muted-foreground">查看账号状态、月度分析用量与数据分享边界。</p></div>
      {error ? <ErrorState description={error} /> : !user || !usage ? <LoadingState label="正在读取账号信息" /> : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="space-y-6">
            <Card className="overflow-hidden p-0">
              <div className="bg-secondary px-6 py-6 text-secondary-foreground"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary">Member profile</p><h2 className="mt-2 text-2xl font-black">公开测试账号</h2></div>
              <dl className="divide-y px-6">
                <div className="grid gap-2 py-5 sm:grid-cols-[2.5rem_10rem_1fr] sm:items-center"><span className="grid h-10 w-10 place-items-center rounded-lg border bg-muted"><Mail className="h-4 w-4 text-primary" aria-hidden="true" /></span><dt className="text-sm text-muted-foreground">邮箱</dt><dd className="break-content font-semibold">{user.email}</dd></div>
                <div className="grid gap-2 py-5 sm:grid-cols-[2.5rem_10rem_1fr] sm:items-center"><span className="grid h-10 w-10 place-items-center rounded-lg border bg-muted"><CalendarDays className="h-4 w-4 text-primary" aria-hidden="true" /></span><dt className="text-sm text-muted-foreground">注册时间</dt><dd className="font-mono text-sm">{new Date(user.created_at).toLocaleString('zh-CN')}</dd></div>
                <div className="grid gap-2 py-5 sm:grid-cols-[2.5rem_10rem_1fr] sm:items-center"><span className="grid h-10 w-10 place-items-center rounded-lg border bg-success/10"><ShieldCheck className="h-4 w-4 text-success" aria-hidden="true" /></span><dt className="text-sm text-muted-foreground">状态</dt><dd className="inline-flex items-center gap-2 font-semibold text-success"><span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden="true" />正常</dd></div>
              </dl>
              <div className="border-t p-6"><Button variant="secondary" onClick={signOut} isLoading={signingOut}><LogOut className="h-4 w-4" aria-hidden="true" />退出登录</Button></div>
            </Card>

            <Card className="p-6"><div className="flex items-start gap-3"><div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border bg-primary/10 text-primary"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></div><div><p className="eyebrow">Privacy boundary</p><h2 className="mt-1 text-lg font-bold">数据与隐私</h2><p className="mt-3 text-pretty text-sm leading-7 text-muted-foreground">公开分享仅包含报告正文、结构化结论与 Evidence。用户信息、API Key、成本和内部执行轨迹不会进入分享页。</p></div></div></Card>
          </div>
          <aside><UsageCard usage={usage} /><Card className="mt-5 p-5"><p className="eyebrow">Single platform</p><h2 className="mt-2 font-bold">当前产品边界</h2><p className="mt-3 text-sm leading-6 text-muted-foreground">仅处理公开可访问的 B 站样本，不提供其他平台入口。</p></Card></aside>
        </div>
      )}
    </AppShell>
  );
}
