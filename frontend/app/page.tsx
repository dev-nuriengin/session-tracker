"use client";

import { useEffect, useState, type ReactNode } from "react";

// Local read view over the tracker's API. Summary-first: load the compact
// overview, drill into the full history only on demand (progressive disclosure).
const API = "http://localhost:8000";

type Overview = {
  project: string;
  next: string | null;
  open_items: number;
  open_preview: string[];
  memory_entries: number;
  last_activity: string | null;
};

type History = {
  project: string;
  open_items: string[];
  memory: { kind: string; title: string | null; content: string; url: string | null }[];
  recent_logs: { kind: string; content: string }[];
};

export default function Home() {
  const [projects, setProjects] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/projects`)
      .then((r) => r.json())
      .then((d) => setProjects(d.projects ?? []))
      .catch(() => setError("Can't reach the API — is the backend running on :8000?"));
  }, []);

  function open(slug: string) {
    setSelected(slug);
    setHistory(null);
    setOverview(null);
    fetch(`${API}/projects/${slug}`)
      .then((r) => r.json())
      .then(setOverview)
      .catch(() => setError("Failed to load overview."));
  }

  function loadFull(slug: string) {
    fetch(`${API}/projects/${slug}/history`)
      .then((r) => r.json())
      .then(setHistory)
      .catch(() => setError("Failed to load history."));
  }

  return (
    <div className="flex min-h-screen bg-zinc-50 font-sans text-zinc-900 dark:bg-black dark:text-zinc-100">
      {/* Sidebar: projects (the summarized entry table) */}
      <aside className="w-64 shrink-0 border-r border-zinc-200 p-4 dark:border-zinc-800">
        <h1 className="mb-1 text-lg font-semibold">Session Tracker</h1>
        <p className="mb-4 text-xs text-zinc-500">local · private</p>
        <nav className="flex flex-col gap-1">
          {projects.map((p) => (
            <button
              key={p}
              onClick={() => open(p)}
              className={`rounded px-3 py-1.5 text-left text-sm transition-colors ${
                selected === p
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-black"
                  : "hover:bg-zinc-200 dark:hover:bg-zinc-800"
              }`}
            >
              {p}
            </button>
          ))}
          {projects.length === 0 && !error && (
            <span className="text-sm text-zinc-500">Loading…</span>
          )}
        </nav>
      </aside>

      {/* Detail: overview first, drill to full on demand */}
      <main className="flex-1 p-8">
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!selected && !error && (
          <p className="text-zinc-500">Pick a project to see its status.</p>
        )}

        {overview && (
          <section className="max-w-2xl">
            <h2 className="mb-4 text-2xl font-semibold">{overview.project}</h2>

            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="open items" value={overview.open_items} />
              <Stat label="memory" value={overview.memory_entries} />
            </div>

            <Field label="Next">
              {overview.next ?? <span className="text-zinc-500">— all done —</span>}
            </Field>

            {overview.open_preview.length > 0 && (
              <Field label="Open (preview)">
                <ul className="list-disc pl-5">
                  {overview.open_preview.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </Field>
            )}

            <Field label="Last activity">
              {overview.last_activity ?? <span className="text-zinc-500">(none)</span>}
            </Field>

            {!history && (
              <button
                onClick={() => loadFull(overview.project)}
                className="mt-4 rounded-full border border-zinc-300 px-4 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                Show full ↓
              </button>
            )}

            {history && (
              <div className="mt-8 space-y-6 border-t border-zinc-200 pt-6 dark:border-zinc-800">
                <FullList title="All open items" items={history.open_items} />
                <div>
                  <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
                    Memory
                  </h3>
                  <ul className="space-y-1 text-sm">
                    {history.memory.map((m, i) => (
                      <li key={i}>
                        <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-xs dark:bg-zinc-800">
                          {m.kind}
                        </span>{" "}
                        {m.content}
                        {m.url && /^https?:\/\//i.test(m.url) && (
                          <a
                            href={m.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-1 text-blue-600 underline"
                          >
                            link
                          </a>
                        )}
                      </li>
                    ))}
                    {history.memory.length === 0 && <li className="text-zinc-500">(none)</li>}
                  </ul>
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
                    Recent session logs
                  </h3>
                  <ul className="space-y-1 text-sm">
                    {history.recent_logs.map((l, i) => (
                      <li key={i}>
                        <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-xs dark:bg-zinc-800">
                          {l.kind}
                        </span>{" "}
                        {l.content}
                      </li>
                    ))}
                    {history.recent_logs.length === 0 && (
                      <li className="text-zinc-500">(none)</li>
                    )}
                  </ul>
                </div>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-zinc-500">{label}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">
        {label}
      </div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function FullList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
        {title}
      </h3>
      <ul className="list-disc pl-5 text-sm">
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
        {items.length === 0 && <li className="text-zinc-500">(none)</li>}
      </ul>
    </div>
  );
}
