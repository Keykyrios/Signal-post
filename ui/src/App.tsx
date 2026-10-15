import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MotionConfig, useReducedMotion } from "motion/react";
import type { Profile, RunReport } from "@/types";
import { day, nameOf } from "@/lib/format";
import { isValid, normalize } from "@/lib/orgnr";
import { useStoredSet } from "@/lib/local";
import { usePalette } from "@/lib/theme";
import { download, profilesToCsv, profilesToJsonl } from "@/lib/export";
import { COMMANDS, PAGE, Sidebar } from "@/components/Sidebar";
import type { JumpResult, SortKey } from "@/components/Filters";
import { Detail } from "@/components/Detail";
import { Overview } from "@/components/Overview";
import ClickSpark from "@/components/react-bits/ClickSpark";
import PixelSwap from "@/components/react-bits/PixelSwap";

type Load =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; profiles: Profile[]; report: RunReport };

async function load(): Promise<{ profiles: Profile[]; report: RunReport }> {
  const res = await fetch("./data/profiles.jsonl", { cache: "no-store" });
  if (!res.ok) throw new Error(`profiles.jsonl returned HTTP ${res.status}`);
  const text = await res.text();
  const profiles: Profile[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      profiles.push(JSON.parse(line) as Profile);
    } catch {
      /* skip a damaged line rather than losing the whole run */
    }
  }
  let report: RunReport = {};
  try {
    const r = await fetch("./data/run_report.json", { cache: "no-store" });
    if (r.ok) report = await r.json();
  } catch {
    /* the report is optional */
  }
  return { profiles, report };
}

const STATUS_COMMANDS: Record<string, string> = {
  "/active": "active",
  "/bankrupt": "bankrupt",
  "/liquidation": "under_liquidation",
  "/deleted": "deleted",
};

export default function App() {
  const c = usePalette();
  const reduce = useReducedMotion();
  const [data, setData] = useState<Load>({ state: "loading" });
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [form, setForm] = useState("");
  const [changedOnly, setChangedOnly] = useState(false);
  const [watchedOnly, setWatchedOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("name");
  const [shown, setShown] = useState(PAGE);
  const [selectedId, setSelectedId] = useState<string | null>(() => location.hash.slice(1) || null);
  const [watched, setWatched] = useStoredSet("signalpost.watched");
  const [reviewed, setReviewed] = useStoredSet("signalpost.reviewed");
  const [toast, setToast] = useState("");
  const toastTimer = useRef<number | undefined>(undefined);

  const say = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 3500);
  }, []);

  useEffect(() => {
    load()
      .then((d) => setData({ state: "ready", ...d }))
      .catch((e: Error) => setData({ state: "error", message: e.message }));
  }, []);

  const profiles = useMemo(() => (data.state === "ready" ? data.profiles : []), [data]);
  const report = data.state === "ready" ? data.report : {};

  const statuses = useMemo(() => {
    const out: Record<string, number> = {};
    for (const p of profiles) out[p.status] = (out[p.status] ?? 0) + 1;
    return out;
  }, [profiles]);

  // Legal form chips: the three most common forms, then Other.
  const { forms, topForms } = useMemo(() => {
    const count: Record<string, number> = {};
    for (const p of profiles) {
      const code = p.facts?.legal_form?.code;
      if (code) count[code] = (count[code] ?? 0) + 1;
    }
    const top = Object.keys(count).sort((a, b) => count[b] - count[a]).slice(0, 3);
    const all = Object.keys(count).length;
    return {
      topForms: new Set(top),
      forms: [
        { value: "all", label: "All" },
        ...top.map((t) => ({ value: t, label: t })),
        ...(all > top.length || profiles.some((p) => !p.facts?.legal_form?.code) ? [{ value: "other", label: "Other" }] : []),
      ],
    };
  }, [profiles]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const digits = q.replace(/\s/g, "");
    const list = profiles.filter((p) => {
      if (status && p.status !== status) return false;
      if (changedOnly && (p.history?.length ?? 0) === 0) return false;
      if (watchedOnly && !watched.has(p.orgnr)) return false;
      if (form) {
        const code = p.facts?.legal_form?.code;
        if (form === "other" ? code && topForms.has(code) : code !== form) return false;
      }
      if (!q) return true;
      return nameOf(p).toLowerCase().includes(q) || p.orgnr.includes(digits);
    });
    const byName = (a: Profile, b: Profile) => nameOf(a).localeCompare(nameOf(b), "nb");
    if (sort === "status") list.sort((a, b) => Number(a.status === "active") - Number(b.status === "active") || byName(a, b));
    else if (sort === "changes") list.sort((a, b) => (b.history?.length ?? 0) - (a.history?.length ?? 0) || byName(a, b));
    else list.sort(byName);
    return list;
  }, [profiles, query, status, form, changedOnly, watchedOnly, watched, sort, topForms]);

  const selected = selectedId ? profiles.find((p) => p.orgnr === selectedId) ?? null : null;
  const activeFilters = [status, form, changedOnly, watchedOnly].filter(Boolean).length;

  const open = useCallback((id: string | null) => {
    setSelectedId(id);
    history.replaceState(null, "", id ? `#${id}` : location.pathname + location.search);
    if (id && window.matchMedia("(max-width: 767px)").matches) {
      requestAnimationFrame(() => document.getElementById("detail")?.scrollIntoView({ block: "start" }));
    }
  }, []);

  const clearAll = useCallback(() => {
    setQuery("");
    setStatus("");
    setForm("");
    setChangedOnly(false);
    setWatchedOnly(false);
    setShown(PAGE);
  }, []);

  // Text from the command bar: slash commands set filters, any other words become the search.
  const find = (text: string) => {
    const words = text.split(/\s+/).filter(Boolean);
    const known = new Set(COMMANDS.map((x) => x.name));
    const unknown = words.filter((w) => w.startsWith("/") && !known.has(w.toLowerCase()));
    const terms = words.filter((w) => !w.startsWith("/"));
    if (words.some((w) => w.toLowerCase() === "/clear")) {
      clearAll();
      say("Search and filters cleared.");
      return;
    }
    for (const w of words.map((x) => x.toLowerCase())) {
      if (STATUS_COMMANDS[w]) setStatus(STATUS_COMMANDS[w]);
      else if (w === "/changed") setChangedOnly(true);
      else if (w === "/watched") setWatchedOnly(true);
    }
    if (terms.length) setQuery(terms.join(" "));
    setShown(PAGE);
    if (unknown.length) say(`Unknown command ${unknown[0]}. Type / to see the list.`);
  };

  const jump = (code: string): JumpResult => {
    const n = normalize(code);
    if (!isValid(n)) return { ok: false, message: "Not a valid organisation number. The check digit does not match." };
    const p = profiles.find((x) => x.orgnr === n);
    if (!p) return { ok: false, message: "Valid number, but it is not in this run." };
    open(p.orgnr);
    return { ok: true, message: `Opened ${nameOf(p)}.` };
  };

  const exportData = (value: string) => {
    if (value === "profile-json") {
      if (!selected) return say("Open a company first, then export it.");
      download(`${selected.orgnr}.json`, JSON.stringify(selected, null, 2), "application/json");
      say(`Downloaded ${selected.orgnr}.json`);
    } else if (value === "copy-orgnr") {
      if (!selected) return say("Open a company first, then copy its number.");
      navigator.clipboard?.writeText(selected.orgnr).then(
        () => say(`Copied ${selected.orgnr}`),
        () => say(`Copy was blocked by the browser. The number is ${selected.orgnr}.`),
      ) ?? say(`Copy is not available here. The number is ${selected.orgnr}.`);
    } else if (value === "list-jsonl") {
      download("signalpost-list.jsonl", profilesToJsonl(rows), "application/x-ndjson");
      say(`Downloaded ${rows.length} profiles as JSON lines.`);
    } else if (value === "list-csv") {
      download("signalpost-list.csv", profilesToCsv(rows), "text/csv");
      say(`Downloaded ${rows.length} profiles as CSV.`);
    } else if (value === "report-json") {
      download("run_report.json", JSON.stringify(report, null, 2), "application/json");
      say("Downloaded run_report.json");
    }
  };

  const ready = data.state === "ready";
  const chipFirst = `${profiles.length.toLocaleString("en-GB")} ${profiles.length === 1 ? "profile" : "profiles"}${report.finished_at ? `, ${day(report.finished_at)}` : ""}`;
  const chipSecond = report.requests_made != null ? `${report.requests_made.toLocaleString("en-GB")} requests, no paid APIs` : "No run report found";

  return (
    <MotionConfig reducedMotion="user">
      <ClickSpark sparkColor={c.accent} sparkCount={8} sparkSize={9} sparkRadius={20} sparkWidth={2} duration={420} disabled={!!reduce} style={{ minHeight: "100dvh" }}>
        <header className="sticky top-0 z-20 flex h-[60px] items-center justify-between gap-4 border-b border-line bg-surface px-4 md:px-6">
          <button type="button" onClick={() => open(null)} className="m-0 rounded-ui bg-transparent p-0 text-lg font-bold tracking-tight text-ink" aria-label="Signalpost overview">
            Signalpost
          </button>
          {ready && (
            <div className="h-7 w-[min(236px,calc(100vw-170px))] shrink-0 text-xs text-muted md:text-[13px]">
              <PixelSwap
                trigger="click"
                pixelSize={6}
                duration={600}
                pattern="left-to-right"
                className="h-7"
                firstContent={<span className="flex h-full w-full items-center justify-end whitespace-nowrap">{chipFirst}</span>}
                secondContent={<span className="flex h-full w-full items-center justify-end whitespace-nowrap">{chipSecond}</span>}
              />
            </div>
          )}
        </header>

        {data.state === "loading" && (
          <div className="grid gap-3 p-6" aria-busy="true" aria-label="Loading profiles">
            {[70, 45, 58].map((w) => (
              <div key={w} className="h-5 animate-pulse rounded-ui bg-line motion-reduce:animate-none" style={{ width: `${w}%` }} />
            ))}
          </div>
        )}

        {data.state === "error" && (
          <div className="max-w-xl p-6">
            <h2 className="mb-2 text-lg font-semibold">The profiles could not be loaded</h2>
            <p className="my-1">{data.message}.</p>
            <p className="my-1">
              Build them with <code className="num">python -m signalpost run --input companies.txt</code>, then open this page with{" "}
              <code className="num">python -m signalpost serve</code>.
            </p>
          </div>
        )}

        {ready && (
          <main className="grid grid-cols-1 md:grid-cols-[minmax(320px,400px)_minmax(0,1fr)]">
            <Sidebar
              rows={rows}
              total={profiles.length}
              shown={shown}
              selectedId={selected?.orgnr ?? null}
              watched={watched}
              reviewed={reviewed}
              statuses={statuses}
              forms={forms}
              status={status}
              form={form}
              changedOnly={changedOnly}
              watchedOnly={watchedOnly}
              sort={sort}
              query={query}
              activeFilters={activeFilters}
              onStatus={(v) => { setStatus(v); setShown(PAGE); }}
              onForm={(v) => { setForm(v); setShown(PAGE); }}
              onChanged={(v) => { setChangedOnly(v); setShown(PAGE); }}
              onSort={setSort}
              onFind={find}
              onClear={clearAll}
              onSelect={(p) => open(p.orgnr)}
              onWatch={(id, on) => { setWatched(id, on); say(on ? "Watching this company." : "Stopped watching."); }}
              onReview={(id, on) => { setReviewed(id, on); say(on ? "Marked reviewed." : "Reopened for review."); }}
              onJump={jump}
              onExport={exportData}
              onMore={() => setShown((n) => n + PAGE)}
            />
            <div id="detail" className="min-w-0">
              {selected ? (
                <Detail
                  key={selected.orgnr}
                  p={selected}
                  watched={watched.has(selected.orgnr)}
                  reviewed={reviewed.has(selected.orgnr)}
                  onWatch={(id, on) => { setWatched(id, on); }}
                  onReview={(id, on) => { setReviewed(id, on); }}
                />
              ) : (
                <Overview
                  profiles={profiles}
                  report={report}
                  watched={watched}
                  reviewed={reviewed}
                  onOpen={(id) => open(id)}
                  onReview={(id, on) => setReviewed(id, on)}
                />
              )}
            </div>
          </main>
        )}

        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed bottom-4 left-1/2 z-30 max-w-[90vw] -translate-x-1/2 transition-opacity duration-150 motion-reduce:transition-none"
          style={{ opacity: toast ? 1 : 0 }}
        >
          {toast && <p className="m-0 rounded-ui border border-line bg-surface px-4 py-2 text-[14px] shadow-[0_4px_16px_-6px_rgba(10,20,40,0.35)]">{toast}</p>}
        </div>
      </ClickSpark>
    </MotionConfig>
  );
}
