import { ReflectionFeed } from "@/components/ReflectionFeed";
import { API_BASE, type Reflection } from "@/lib/api";

async function fetchReflections(): Promise<Reflection[]> {
  try {
    const r = await fetch(`${API_BASE}/api/reflection?limit=30`, { cache: "no-store" });
    if (!r.ok) return [];
    return (await r.json()) as Reflection[];
  } catch {
    return [];
  }
}

export default async function ReflectionPage() {
  const items = await fetchReflections();
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-4xl">反思</h1>
        <p className="muted mt-1">
          日间与周间反思，用克制的语气写成，替你留一面安静的镜子。
        </p>
      </header>
      <ReflectionFeed items={items} />
    </div>
  );
}
