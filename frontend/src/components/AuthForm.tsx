'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Check, Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { Button, Card, Input } from '@/components/ui';
import { login, readableError, register } from '@/lib/api';

export function AuthForm({ mode }: { mode: 'login' | 'register' }) {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (mode === 'register' && password !== confirm) {
      setFieldError('两次输入的密码不一致，请重新确认。');
      return;
    }
    setLoading(true);
    setError('');
    setFieldError('');
    try {
      if (mode === 'register') await register(email, password);
      else await login(email, password);
      const requestedNext = new URLSearchParams(window.location.search).get('next');
      const nextPath = requestedNext?.startsWith('/') && !requestedNext.startsWith('//') ? requestedNext : '/dashboard';
      router.replace(nextPath);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="editorial-grid min-h-[calc(100dvh-4rem)] border-b">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-10 sm:px-6 sm:py-14 lg:grid-cols-[minmax(0,.92fr)_minmax(28rem,.68fr)] lg:items-stretch lg:px-8 lg:py-16">
        <section className="relative hidden min-h-[38rem] overflow-hidden rounded-2xl bg-secondary p-10 text-secondary-foreground shadow-float lg:flex lg:flex-col">
          <div className="halftone absolute -right-12 -top-12 h-56 w-56 opacity-25" />
          <div className="speed-lines absolute inset-x-0 bottom-0 h-48 opacity-30" />
          <p className="eyebrow relative">Member access / 01</p>
          <h1 className="title-balance relative mt-6 max-w-xl text-5xl font-black leading-[1.05] tracking-[-.055em]">把每条判断，<br />连回真实来源。</h1>
          <p className="relative mt-6 max-w-lg text-base leading-8 text-secondary-foreground/72">登录后继续管理 B 站研究任务、Evidence、报告与用量。这里是内容研究工作台，不是泛平台数据看板。</p>
          <div className="relative mt-auto grid gap-3">
            {['HttpOnly Cookie 会话', '报告与 Evidence 按账号隔离', '公开分享不包含用户与成本信息'].map((item, index) => (
              <div key={item} className="grid grid-cols-[2rem_1fr_auto] items-center gap-3 border-t border-white/20 py-3 text-sm">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/10"><Check className="h-4 w-4 text-primary" aria-hidden="true" /></span>
                <span>{item}</span><span className="font-mono text-[10px] text-secondary-foreground/50">0{index + 1}</span>
              </div>
            ))}
          </div>
        </section>

        <Card className="self-center bg-surface-elevated p-6 shadow-float sm:p-8 lg:p-10">
          <div className="flex items-start justify-between gap-4 border-b pb-6">
            <div><p className="eyebrow">{mode === 'login' ? 'Welcome back' : 'Open beta'}</p><h1 className="title-balance mt-2 text-3xl font-black tracking-[-.04em]">{mode === 'login' ? '登录研究工作台' : '创建公开测试账号'}</h1></div>
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border bg-primary/10 text-primary"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></div>
          </div>
          <p className="mt-5 text-pretty text-sm leading-6 text-muted-foreground">{mode === 'login' ? '继续查看你的任务、报告和分析用量。' : '当前仅用于小规模 B 站单平台分析测试。'}</p>

          <form className="mt-7 space-y-5" onSubmit={submit} noValidate>
            <div>
              <label htmlFor="auth-email" className="text-sm font-semibold">邮箱</label>
              <Input id="auth-email" className="mt-2" type="email" required autoComplete="email" inputMode="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            </div>
            <div>
              <label htmlFor="auth-password" className="text-sm font-semibold">密码</label>
              <div className="relative mt-2">
                <Input id="auth-password" className="pr-12" type={showPassword ? 'text' : 'password'} required minLength={8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={(event) => setPassword(event.target.value)} aria-describedby="password-hint" placeholder="至少 8 位" />
                <Button variant="ghost" size="sm" className="absolute right-0.5 top-0.5 w-11 px-0" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? '隐藏密码' : '显示密码'}>
                  {showPassword ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
                </Button>
              </div>
              <p id="password-hint" className="mt-2 text-xs text-muted-foreground">密码至少 8 位，支持浏览器密码管理器自动填充。</p>
            </div>
            {mode === 'register' && (
              <div>
                <label htmlFor="auth-confirm" className="text-sm font-semibold">确认密码</label>
                <Input id="auth-confirm" className="mt-2" type={showPassword ? 'text' : 'password'} required minLength={8} autoComplete="new-password" value={confirm} onChange={(event) => { setConfirm(event.target.value); setFieldError(''); }} aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? 'confirm-error' : undefined} />
                {fieldError && <p id="confirm-error" className="mt-2 text-sm font-medium text-destructive" role="alert">{fieldError}</p>}
              </div>
            )}
            {error && <div className="rounded-lg border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive" role="alert">{error}</div>}
            <Button className="w-full" size="lg" type="submit" isLoading={loading}>{mode === 'login' ? '登录' : '注册并进入工作台'}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">{mode === 'login' ? '还没有账号？' : '已有账号？'} <Link className="font-semibold text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary" href={mode === 'login' ? '/register' : '/login'}>{mode === 'login' ? '注册公开测试账号' : '返回登录'}</Link></p>
        </Card>
      </div>
    </main>
  );
}
