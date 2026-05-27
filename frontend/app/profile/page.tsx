import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ProfilePage() {
  let profile = null;
  try {
    profile = await api.profile();
  } catch (e) {
    profile = null;
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs uppercase tracking-widest muted">L3 · 长期画像</div>
        <h1 className="mt-2 font-serif text-3xl tracking-tight">profile.md</h1>
        <p className="mt-1 text-sm muted">
          由 DelayedMemoryWriter 维护。你也可以直接在文件系统编辑：
          {profile?.path && <code className="ml-2 text-xs">{profile.path}</code>}
        </p>
      </div>

      <div className="card">
        <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
          {profile?.markdown || "profile.md 还未生成。先做几次签到或对话。"}
        </pre>
      </div>
    </div>
  );
}
