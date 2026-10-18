'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Eye, EyeOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button, Card, Input } from '@/components/ui';
import { login, readableError, register } from '@/lib/api';

function returnPath() {
  const requested = new URLSearchParams(window.location.search).get('next');
  if (!requested?.startsWith('/')) return '/dashboard';
  try {
    const url = new URL(requested, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : '/dashboard';
  } catch { return '/dashboard'; }
}

export function AuthForm({ mode }: { mode: 'login' | 'register' }) {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [loading, setLoading] = useState(false);
  const [nextPath, setNextPath] = useState('/dashboard');
  useEffect(() => { setNextPath(returnPath()); }, []);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
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
      router.replace(returnPath());
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-[calc(100dvh-4rem)]">
      <div className="mx-auto max-w-[29rem] px-4 py-12 sm:px-6 sm:py-20">
        <Card className="bg-surface-elevated p-6 sm:p-9">
          <h1 className="title-balance text-center font-display text-3xl font-semibold tracking-tight">{mode === 'login' ? '回到你的工作台' : '创建你的账号'}</h1>
          <p className="mt-3 text-pretty text-center text-sm leading-6 text-muted-foreground">{mode === 'login' ? '继续查看你的任务、报告和分析用量。' : '当前仅用于小规模 B 站单平台分析测试。'}</p>

          <form className="mt-8 space-y-5" onSubmit={submit} noValidate>
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

          <p className="mt-6 text-center text-sm text-muted-foreground">{mode === 'login' ? '还没有账号？' : '已有账号？'} <Link className="font-semibold text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary" href={`${mode === 'login' ? '/register' : '/login'}?next=${encodeURIComponent(nextPath)}`}>{mode === 'login' ? '注册公开测试账号' : '返回登录'}</Link></p>
        </Card>
      </div>
    </main>
  );
}
