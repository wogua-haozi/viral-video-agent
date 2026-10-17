import type { Metadata } from 'next';
import { ThemeProvider } from '@/components/ThemeProvider';
import { Header } from '@/components/Header';
import './globals.css';

export const metadata: Metadata = {
  title: '爆款视频分析',
  description: '用真实 B 站样本生成带来源、Evidence 与可执行建议的内容分析报告',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
          <div className="relative flex min-h-screen flex-col">
            <a className="skip-link" href="#main-content">跳到主要内容</a>
            <Header />
            <div id="main-content" className="flex-1" tabIndex={-1}>{children}</div>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
