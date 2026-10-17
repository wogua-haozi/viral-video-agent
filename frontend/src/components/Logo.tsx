import Image from 'next/image';
import Link from 'next/link';
import { cn } from '@/lib/utils';

export function Logo({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link href="/" className={cn('inline-flex min-h-11 items-center gap-2.5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', className)} aria-label="爆款视频分析首页">
      <Image src="/logo-mark.svg" alt="" width={36} height={36} priority className="shrink-0" />
      {!compact && <span className="whitespace-nowrap font-display text-[15px] font-bold tracking-[.02em] sm:text-base">爆款视频分析</span>}
    </Link>
  );
}
