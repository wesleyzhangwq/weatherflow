import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "WeatherFlow",
  description: "面向长期自我成长的本地 AI 伴侣。"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen font-sans">
        <header className="border-b border-black/5 dark:border-white/10">
          <div className="mx-auto max-w-5xl px-6 py-4 flex items-center justify-between">
            <Link href="/" className="font-serif text-2xl tracking-tight">
              WeatherFlow
            </Link>
            <nav className="flex gap-5 text-sm muted">
              <Link href="/" className="hover:opacity-80">今日</Link>
              <Link href="/checkin" className="hover:opacity-80">签到</Link>
              <Link href="/reflection" className="hover:opacity-80">反思</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-5xl px-6 py-10 text-xs muted">
          长期陪伴 · 本地优先 · 以记忆为中心
        </footer>
      </body>
    </html>
  );
}
