import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { FilterIcon } from "@hugeicons/core-free-icons";
import type { Profile } from "@/types";
import PromptBar from "@/components/react-bits/PromptBar";
import { TextMorph } from "@/components/componentry/TextMorph";
import { CompanyRow } from "@/components/CompanyRow";
import { Filters, type JumpResult, type SortKey } from "@/components/Filters";
import { usePalette } from "@/lib/theme";

export const PAGE = 150;

export const COMMANDS = [
  { key: "active", name: "/active", description: "Only active companies" },
  { key: "bankrupt", name: "/bankrupt", description: "Only bankrupt companies" },
  { key: "liquidation", name: "/liquidation", description: "Only companies under liquidation" },
  { key: "deleted", name: "/deleted", description: "Only entities removed from the register" },
  { key: "changed", name: "/changed", description: "Only profiles that changed" },
  { key: "watched", name: "/watched", description: "Only companies you are watching" },
  { key: "clear", name: "/clear", description: "Reset the search and every filter" },
];

interface Props {
  rows: Profile[];
  total: number;
  shown: number;
  selectedId: string | null;
  watched: Set<string>;
  reviewed: Set<string>;
  statuses: Record<string, number>;
  forms: { value: string; label: string }[];
  status: string;
  form: string;
  changedOnly: boolean;
  watchedOnly: boolean;
  sort: SortKey;
  query: string;
  activeFilters: number;
  onStatus: (v: string) => void;
  onForm: (v: string) => void;
  onChanged: (v: boolean) => void;
  onSort: (v: SortKey) => void;
  onFind: (text: string) => void;
  onClear: () => void;
  onSelect: (p: Profile) => void;
  onWatch: (id: string, on: boolean) => void;
  onReview: (id: string, on: boolean) => void;
  onJump: (code: string) => JumpResult;
  onExport: (value: string) => void;
  onMore: () => void;
}

export function Sidebar(p: Props) {
  const c = usePalette();
  const [open, setOpen] = useState(false);

  return (
    <aside
      className="flex h-[72dvh] min-h-0 flex-col border-b border-line bg-surface md:sticky md:top-[60px] md:h-[calc(100dvh-60px)] md:border-r md:border-b-0"
      aria-label="Companies"
    >
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="filters-panel"
          className="inline-flex items-center gap-2 rounded-ui border border-line bg-bg px-3 py-1.5 text-[14px] active:translate-y-px motion-reduce:active:translate-y-0"
        >
          <HugeiconsIcon icon={FilterIcon} size={16} strokeWidth={1.8} aria-hidden="true" />
          Filters and lookup
          {p.activeFilters > 0 && <span className="num text-accent">{p.activeFilters}</span>}
        </button>
        <span className="text-[13px] text-muted" aria-live="polite">
          <span className="num">{p.rows.length}</span> of <span className="num">{p.total}</span>
        </span>
      </div>

      {open && (
        <div id="filters-panel" className="max-h-[56%] overflow-auto overscroll-contain">
          <Filters
            statuses={p.statuses}
            total={p.total}
            forms={p.forms}
            status={p.status}
            form={p.form}
            changedOnly={p.changedOnly}
            sort={p.sort}
            onStatus={p.onStatus}
            onForm={p.onForm}
            onChanged={p.onChanged}
            onSort={p.onSort}
            onJump={p.onJump}
            onExport={p.onExport}
          />
        </div>
      )}

      {(p.query || p.activeFilters > 0) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2 text-[13px] text-muted">
          <span className="truncate">{p.query ? `Search: ${p.query}` : "Filters applied"}</span>
          <button type="button" onClick={p.onClear} className="shrink-0 text-accent underline underline-offset-2">
            Clear all
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto overscroll-contain" role="list" aria-label="Company list">
        {p.rows.length === 0 ? (
          <div className="px-4 py-8 text-muted">
            <p className="m-0">
              No companies match. Try a{" "}
              <TextMorph words={["company name", "organisation number", "status command"]} interval={2200} className="align-text-bottom font-semibold text-ink" />
              {" "}or clear the filters.
            </p>
            <button type="button" onClick={p.onClear} className="mt-3 rounded-ui border border-accent px-3.5 py-2 text-accent">
              Clear all
            </button>
          </div>
        ) : (
          p.rows.slice(0, p.shown).map((row) => (
            <div key={row.orgnr} role="listitem" className="border-b border-line">
              <CompanyRow
                p={row}
                selected={row.orgnr === p.selectedId}
                watched={p.watched.has(row.orgnr)}
                reviewed={p.reviewed.has(row.orgnr)}
                onSelect={p.onSelect}
                onWatch={p.onWatch}
                onReview={p.onReview}
              />
            </div>
          ))
        )}
        {p.rows.length > p.shown && (
          <button type="button" onClick={p.onMore} className="mx-4 my-3 rounded-ui border border-accent px-3.5 py-2 text-accent active:translate-y-px">
            Show {Math.min(PAGE, p.rows.length - p.shown)} more
          </button>
        )}
      </div>

      <div className="border-t border-line p-3">
        <PromptBar
          placeholder="Name, number or /command"
          commands={COMMANDS}
          sources={[]}
          models={[]}
          efforts={[]}
          onSend={(text) => p.onFind(text)}
          background={c.bg}
          color={c.ink}
          menuBackground={c.surface}
          sparkColor={c.accent}
          width={400}
          radius={8}
          maxRows={2}
          className="mx-auto [&_[aria-label='Add_files_and_sources']]:hidden"
        />
      </div>
    </aside>
  );
}
