'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from 'next-themes';
import { BarChart3, FilePlus2, Files, Gauge, Menu, Moon, Settings, Sun, UserRound, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Logo } from '@/components/Logo';
import { Button } from '@/components/ui';
import { cn } from '@/lib/utils';

const items = [
  { href: '/dashboard', label: '创作工作台', kicker: 'Overview', icon: Gauge, active: (path: string) => path === '/dashboard' },
  { href: '/jobs/new', label: '新建分析', kicker: '创建任务', icon: FilePlus2, active: (path: string) => path === '/jobs/new' },
  { href: '/history', label: '任务与报告', kicker: '历史记录', icon: Files, active: (path: string) => path === '/history' || /^\/jobs\/(?!new)/.test(path) || path.startsWith('/reports/') || path.startsWith('/report/') },
  { href: '/examples', label: '示例报告', kicker: '公开样例', icon: BarChart3, active: (path: string) => path.startsWith('/examples') },
  { href: '/settings', label: '设置与用量', kicker: '账户', icon: Settings, active: (path: string) => path.startsWith('/settings') },
];

function ThemeButton() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = mounted && resolvedTheme === 'dark';
  return (
    <Button
      variant="ghost"
      size="sm"
      className="relative w-11 px-0"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label={mounted ? (isDark ? '切换到浅色主题' : '切换到深色主题') : '切换主题'}
    >
      <Sun className="h-4 w-4 scale-100 transition-transform dark:scale-0" aria-hidden="true" />
      <Moon className="absolute h-4 w-4 scale-0 transition-transform dark:scale-100" aria-hidden="true" />
    </Button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const trigger = openButtonRef.current;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
      if (event.key === 'Tab') {
        const focusable = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])') ?? []);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = previousOverflow;
      trigger?.focus();
    };
  }, [open]);

  const navigation = (
    <nav className="space-y-1.5" aria-label="工作台导航">
      {items.map(({ href, label, kicker, icon: Icon, active }) => {
        const selected = active(pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={selected ? 'page' : undefined}
            className={cn(
      'group grid min-h-14 grid-cols-[2.5rem_1fr_auto] items-center gap-2 rounded-lg border border-transparent px-2.5 text-sm transition-[background-color,border-color,color] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              selected ? 'border-primary/20 bg-primary/10 text-foreground' : 'text-muted-foreground hover:border-border hover:bg-muted/70 hover:text-foreground',
            )}
          >
            <span className={cn('grid h-9 w-9 place-items-center rounded-lg border bg-background transition-colors', selected && 'border-primary/30 text-primary')}><Icon className="h-4 w-4" aria-hidden="true" /></span>
            <span><span className="block font-semibold">{label}</span><span className="block text-[10px] uppercase tracking-[.12em] text-muted-foreground">{kicker}</span></span>
            {selected && <span className="h-6 w-1 rounded-full bg-primary" aria-hidden="true" />}
          </Link>
        );
      })}
    </nav>
  );

  const accountActions = (
    <div className="flex items-center gap-1.5">
      <ThemeButton />
      <Link href="/settings" className="grid min-h-11 w-11 place-items-center rounded-lg border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="打开账号设置">
        <UserRound className="h-4 w-4" aria-hidden="true" />
      </Link>
    </div>
  );

  return (
    <div className="min-h-dvh bg-background">
      <aside className="fixed inset-y-0 left-0 z-50 hidden w-[17rem] flex-col overflow-y-auto border-r bg-surface p-5 print:hidden lg:flex">
        <div className="absolute inset-x-0 top-0 h-px bg-primary/60" />
        <Logo />
        <div className="mb-1 mt-7 border-y py-5"><p className="eyebrow">The creator’s study</p><p className="mt-2 font-display text-sm text-muted-foreground">以真实样本，照见创作方向。</p></div>
        <div className="mt-6">{navigation}</div>
        <div className="mt-auto pt-10">
          <div className="studio-hero rounded-lg border p-4">
          <p className="eyebrow text-[10px]">Evidence first</p>
          <strong className="mt-2 block font-display text-base font-normal">每一个判断，都有来处。</strong>
          <p className="mt-2 text-xs leading-6 text-[#c4b49b]">研究范围：B 站公开样本。结论保留来源与局限。</p>
          </div>
        </div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 bg-secondary/60 backdrop-blur-sm lg:hidden" role="dialog" aria-modal="true" aria-label="工作台移动导航" onMouseDown={(event) => { if (event.currentTarget === event.target) setOpen(false); }}>
          <aside ref={drawerRef} className="motion-enter flex h-dvh w-[min(22rem,88vw)] flex-col overflow-y-auto border-r bg-surface-elevated p-5 shadow-float">
            <div className="flex items-center justify-between gap-4 border-b pb-4"><Logo /><Button ref={closeButtonRef} variant="ghost" size="sm" className="w-11 px-0" onClick={() => setOpen(false)} aria-label="关闭菜单"><X className="h-5 w-5" aria-hidden="true" /></Button></div>
            <div className="mt-6">{navigation}</div>
            <div className="mt-auto border-t pt-5 text-xs text-muted-foreground">公开样本 · 来源可回看 · 结论可追溯</div>
          </aside>
        </div>
      )}

      <div className="app-content lg:pl-[17rem]">
        <header className="sticky top-0 z-40 flex min-h-16 items-center justify-between border-b bg-background/92 px-4 backdrop-blur-xl print:hidden sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Button ref={openButtonRef} variant="ghost" size="sm" className="w-11 px-0 lg:hidden" onClick={() => setOpen(true)} aria-label="打开菜单" aria-expanded={open}><Menu className="h-5 w-5" aria-hidden="true" /></Button>
            <div className="min-w-0"><p className="hidden font-mono text-[10px] uppercase tracking-[.18em] text-muted-foreground sm:block">Viral Video Agent / Studio</p><p className="truncate font-display text-sm">B 站内容研究手记</p></div>
          </div>
          {accountActions}
        </header>
        <main className="mx-auto max-w-[90rem] px-4 py-7 sm:px-6 sm:py-9 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
