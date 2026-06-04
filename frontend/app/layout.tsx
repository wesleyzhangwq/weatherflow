import type { Metadata } from "next";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "WeatherFlow",
  description: "节奏镜像 + 日常驾驶舱。Calendar + GitHub。"
};

const themeInitScript = `
(() => {
  try {
    const key = "weatherflow.theme";
    const stored = window.localStorage.getItem(key);
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const resolved = stored === "day" ? "day" : stored === "night" ? "night" : systemDark ? "night" : "day";
    document.documentElement.classList.toggle("dark", resolved === "night");
    document.documentElement.style.colorScheme = resolved === "night" ? "dark" : "light";
  } catch {
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "light";
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-screen font-sans">
        <header className="border-b border-black/5 dark:border-white/10">
          <div className="mx-auto flex max-w-5xl flex-col gap-3 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
            <Link href="/" className="font-serif text-2xl tracking-tight">
              WeatherFlow
            </Link>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
              <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm muted">
                <Link href="/" className="hover:opacity-80">节奏</Link>
                <Link href="/checkin" className="hover:opacity-80">签到</Link>
                <Link href="/chat" className="hover:opacity-80">对话</Link>
                <Link href="/profile" className="hover:opacity-80">画像</Link>
              </nav>
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-5xl px-6 py-10 text-xs muted">
          节奏镜像 · 日常驾驶舱 · 本地优先 · v1
        </footer>
      </body>
    </html>
  );
}
