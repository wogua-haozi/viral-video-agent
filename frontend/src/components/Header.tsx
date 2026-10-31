'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Menu, Moon, Sun, X } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useRef, useState } from 'react';
import { Logo } from '@/components/Logo';
import { Button, LinkButton } from '@/components/ui';

const navItems = [
  { href: '/#templates', label: '分析模板' },
  { href: '/#evidence', label: '来源与依据' },
  { href: '/examples', label: '示例报告' },
];

export function HeaderActions() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-1 sm:gap-2">
      <Button
        variant="ghost"
        size="sm"
        className="relative w-11 px-0"
        onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
        aria-label={!mounted ? '切换主题' : resolvedTheme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
      >
        <Sun className="h-4 w-4 scale-100 transition-transform motion-reduce:transition-none dark:scale-0" aria-hidden="true" />
        <Moon className="absolute h-4 w-4 scale-0 transition-transform motion-reduce:transition-none dark:scale-100" aria-hidden="true" />
      </Button>
      <Link href="/login" className="hidden min-h-11 items-center rounded-full px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none sm:inline-flex">登录</Link>
      <LinkButton href="/jobs/new" size="sm" className="min-w-0 shrink whitespace-normal py-2 text-center">进入工作台</LinkButton>
    </div>
  );
}

export function Header() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const isAppPage = ['/dashboard', '/jobs', '/reports', '/report', '/history', '/settings'].some((prefix) => pathname.startsWith(prefix));

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

  if (isAppPage) return null;
  return (
    <>
      <header className="navigation-material sticky top-0 z-40 border-b border-border/60 print:hidden">
        <div className="mx-auto flex min-h-16 max-w-7xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2 sm:px-6 lg:px-8">
          <Logo className="min-w-11 [&>span]:hidden min-[420px]:[&>span]:inline" />
          <nav className="hidden flex-wrap items-center justify-center gap-1 lg:flex" aria-label="公共导航">
            {navItems.map((item) => (
              <Link key={item.href} href={item.href} className="inline-flex min-h-11 items-center rounded-full px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none">
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-1 lg:flex-initial">
            <HeaderActions />
            <Button ref={openButtonRef} variant="ghost" size="sm" className="w-11 px-0 lg:hidden" onClick={() => setOpen(true)} aria-label="打开导航菜单" aria-expanded={open}>
              <Menu className="h-5 w-5" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </header>

      {open && (
        <div className="modal-scrim fixed inset-0 z-50 print:hidden lg:hidden" role="dialog" aria-modal="true" aria-label="移动导航" onMouseDown={(event) => { if (event.currentTarget === event.target) setOpen(false); }}>
          <div ref={drawerRef} className="motion-enter ml-auto flex h-dvh w-[min(22rem,88vw)] flex-col overflow-y-auto overscroll-contain border-l border-border/60 bg-surface-elevated p-5 shadow-float">
            <div className="flex items-center justify-between gap-3 border-b border-border/60 pb-5">
              <Logo className="min-w-0 [&>span]:min-w-0 [&>span]:whitespace-normal" />
              <Button ref={closeButtonRef} variant="ghost" size="sm" className="w-11 px-0" onClick={() => setOpen(false)} aria-label="关闭导航菜单"><X className="h-5 w-5" aria-hidden="true" /></Button>
            </div>
            <nav className="mt-6 space-y-1" aria-label="移动端公共导航">
              {navItems.map((item) => (
                <Link key={item.href} href={item.href} onClick={() => setOpen(false)} className="flex min-h-12 items-center rounded-lg px-4 py-3 text-base font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none">
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="mt-auto pt-8">
              <p className="text-sm leading-6 text-muted-foreground">当前仅支持公开可访问的 B 站样本。</p>
              <LinkButton href="/login" variant="secondary" className="mt-4 w-full">登录工作台</LinkButton>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
