'use client';

import Link, { type LinkProps } from 'next/link';
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';
import { AlertCircle, Inbox, Loader2, X } from 'lucide-react';
import { cn } from '@/lib/utils';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

export function buttonStyles({ variant = 'primary', size = 'md', className }: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}) {
  return cn(
    'inline-flex shrink-0 items-center justify-center gap-2 rounded-lg font-semibold transition-[color,background-color,border-color,box-shadow,transform] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:translate-y-px disabled:pointer-events-none disabled:opacity-50 motion-reduce:transition-none',
    variant === 'primary' && 'border border-primary bg-primary text-primary-foreground shadow-[0_8px_24px_hsl(var(--primary)/.18)] hover:bg-primary/90 hover:shadow-[0_10px_28px_hsl(var(--primary)/.24)]',
    variant === 'secondary' && 'border border-foreground/20 bg-card text-foreground shadow-sm hover:border-foreground/40 hover:bg-muted/70',
    variant === 'ghost' && 'border border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
    variant === 'danger' && 'border border-destructive bg-destructive text-destructive-foreground hover:bg-destructive/90',
    size === 'sm' && 'min-h-11 px-3 text-sm',
    size === 'md' && 'min-h-11 px-4 text-sm',
    size === 'lg' && 'min-h-12 px-5 text-base',
    className,
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', isLoading = false, disabled, children, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={buttonStyles({ variant, size, className })}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      {...props}
    >
      {isLoading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
      {children}
    </button>
  ),
);
Button.displayName = 'Button';

type LinkButtonProps = LinkProps & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export function LinkButton({ className, variant = 'primary', size = 'md', ...props }: LinkButtonProps) {
  return <Link className={buttonStyles({ variant, size, className })} {...props} />;
}

const fieldStyles = 'w-full rounded-lg border border-input bg-surface-elevated text-foreground shadow-[inset_0_1px_0_hsl(var(--foreground)/.03)] outline-none transition-[border-color,box-shadow,background-color] duration-200 placeholder:text-muted-foreground/75 hover:border-foreground/40 focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn(fieldStyles, 'min-h-12 px-3.5 text-base sm:text-sm', className)} {...props} />
));
Input.displayName = 'Input';

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn(fieldStyles, 'min-h-12 px-3.5 text-base sm:text-sm', className)} {...props} />
));
Select.displayName = 'Select';

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(fieldStyles, 'min-h-32 resize-y p-3.5 text-base leading-7 sm:text-sm', className)} {...props} />
));
Textarea.displayName = 'Textarea';

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-xl border bg-card text-card-foreground shadow-editorial', className)} {...props} />;
}

const statusStyles: Record<string, string> = {
  pending: 'border-foreground/20 bg-muted text-foreground',
  running: 'border-info/30 bg-info/10 text-info',
  waiting_user: 'border-warning/50 bg-warning/20 text-warning-foreground dark:text-warning',
  waiting_candidate_confirmation: 'border-info/40 bg-info/10 text-info',
  completed: 'border-success/30 bg-success/10 text-success',
  partial: 'border-warning/50 bg-warning/20 text-warning-foreground dark:text-warning',
  failed: 'border-destructive/30 bg-destructive/10 text-destructive',
  cancelled: 'border-foreground/20 bg-muted text-muted-foreground',
};
const statusDots: Record<string, string> = {
  pending: 'bg-muted-foreground',
  running: 'bg-info',
  waiting_user: 'bg-warning',
  waiting_candidate_confirmation: 'bg-info',
  completed: 'bg-success',
  partial: 'bg-warning',
  failed: 'bg-destructive',
  cancelled: 'bg-muted-foreground',
};
const statusLabels: Record<string, string> = {
  pending: '排队中',
  running: '分析中',
  waiting_user: '待补充',
  waiting_candidate_confirmation: '待确认候选',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
  cancelled: '已取消',
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] font-semibold', statusStyles[status] ?? statusStyles.pending)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', statusDots[status] ?? statusDots.pending)} aria-hidden="true" />
      {statusLabels[status] ?? status}
    </span>
  );
}

export function EmptyState({ title = '暂无内容', description, action }: { title?: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-xl border bg-muted/60"><Inbox className="h-5 w-5 text-muted-foreground" aria-hidden="true" /></div>
      <p className="eyebrow mt-5">Empty state</p>
      <h3 className="mt-2 text-lg font-bold">{title}</h3>
      {description && <p className="mt-2 max-w-md text-pretty text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = '加载失败', description = '请稍后重试。', action }: { title?: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center" role="alert">
      <div className="grid h-12 w-12 place-items-center rounded-xl border border-destructive/25 bg-destructive/10"><AlertCircle className="h-5 w-5 text-destructive" aria-hidden="true" /></div>
      <p className="eyebrow mt-5 text-destructive">Request error</p>
      <h3 className="mt-2 text-lg font-bold">{title}</h3>
      <p className="mt-2 max-w-md text-pretty text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-lg bg-muted motion-reduce:animate-none', className)} aria-hidden="true" />;
}

export function LoadingState({ label = '正在加载' }: { label?: string }) {
  return (
    <div className="flex min-h-56 items-center justify-center gap-3 text-sm text-muted-foreground" role="status" aria-live="polite">
      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      {label}
    </div>
  );
}

export function Modal({ open, title, children, onClose }: { open: boolean; title: string; children: React.ReactNode; onClose: () => void }) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
      if (event.key === 'Tab') {
        const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
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
      previousFocus.current?.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[70] grid place-items-center bg-secondary/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}
    >
      <div ref={dialogRef} className="w-full max-w-lg">
        <Card className="motion-enter max-h-[min(760px,calc(100dvh-2rem))] overflow-y-auto bg-surface-elevated p-5 shadow-float sm:p-6">
          <div className="mb-5 flex items-center justify-between gap-4 border-b pb-4">
            <div><p className="eyebrow">Dialog</p><h2 id={titleId} className="mt-1 text-lg font-bold">{title}</h2></div>
            <Button ref={closeRef} variant="ghost" size="sm" className="w-11 px-0" onClick={onClose} aria-label="关闭对话框"><X className="h-5 w-5" aria-hidden="true" /></Button>
          </div>
          {children}
        </Card>
      </div>
    </div>
  );
}

export function Toast({ message }: { message: string }) {
  return (
    <div className="fixed bottom-5 right-5 z-[80] max-w-[calc(100vw-2.5rem)] rounded-lg border border-white/10 bg-secondary px-4 py-3 text-sm font-medium text-secondary-foreground shadow-float" role="status" aria-live="polite">
      {message}
    </div>
  );
}
