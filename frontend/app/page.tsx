import Link from "next/link";
import { HypothesisStack } from "@/components/HypothesisStack";
import { DataStrip } from "@/components/DataStrip";
import { AmbientFooter } from "@/components/AmbientFooter";
import { CurrentStateWidget } from "@/components/CurrentStateWidget";

export default async function Home() {
  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest muted">
            WeatherFlow · 节奏镜像
          </div>
          <h1 className="mt-2 font-serif text-4xl tracking-tight">
            你现在的节奏
          </h1>
          <p className="mt-1 text-sm muted">
            最多 3 张卡片。校准为「准」会进入长期画像，校准后下方小卡升级。
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/chat"
            className="rounded-lg border border-black/10 dark:border-white/20 px-4 py-2 text-sm"
          >
            打开 Chat
          </Link>
          <Link
            href="/checkin"
            className="rounded-lg bg-black px-4 py-2 text-sm text-white dark:bg-white dark:text-black"
          >
            做一次签到
          </Link>
        </div>
      </section>

      <section>
        <DataStrip />
      </section>

      <section>
        <CurrentStateWidget />
      </section>

      <section>
        <HypothesisStack />
      </section>

      <section>
        <AmbientFooter />
      </section>
    </div>
  );
}
