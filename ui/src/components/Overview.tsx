import { useMemo } from "react";
import { useReducedMotion } from "motion/react";
import WebGLLiquid from "@/components/componentry/WebGLLiquid";
import { Counted } from "@/components/Counted";
import Shredder from "@/components/react-bits/Shredder";
import FolderFloat from "@/components/react-bits/FolderFloat";
import type { Profile, RunReport } from "@/types";
import { nameOf, statusLabel } from "@/lib/format";
import { usePalette } from "@/lib/theme";

interface Props {
  profiles: Profile[];
  report: RunReport;
  watched: Set<string>;
  reviewed: Set<string>;
  onOpen: (id: string) => void;
  onReview: (id: string, on: boolean) => void;
}

// Shredder draws every card it is given, so the queue is a short stack that refills as cards are reviewed.
const QUEUE_SIZE = 4;

interface QueueItem {
  id: string;
  p: Profile;
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div>
      <dt className="text-[13px] text-white/75">{label}</dt>
      <dd className="m-0 text-[28px] leading-tight font-bold tracking-tight">
        <Counted value={value} className="num" />
      </dd>
    </div>
  );
}

export function Overview({ profiles, report, watched, reviewed, onOpen, onReview }: Props) {
  const c = usePalette();
  const reduce = useReducedMotion();

  const stats = useMemo(() => {
    let withAccounts = 0, changed = 0, flagged = 0;
    for (const p of profiles) {
      if (p.facts?.revenue) withAccounts++;
      if ((p.history?.length ?? 0) > 0) changed++;
      if (p.status !== "active") flagged++;
    }
    return { withAccounts, changed, flagged };
  }, [profiles]);

  // Needs a look: not active, or changed since it was first checked. Reviewed ones leave the queue.
  const queue: QueueItem[] = useMemo(
    () =>
      profiles
        .filter((p) => !reviewed.has(p.orgnr) && (p.status !== "active" || (p.history?.length ?? 0) > 0))
        .slice(0, QUEUE_SIZE)
        .map((p) => ({ id: p.orgnr, p })),
    [profiles, reviewed],
  );
  const queueTotal = useMemo(
    () => profiles.filter((p) => !reviewed.has(p.orgnr) && (p.status !== "active" || (p.history?.length ?? 0) > 0)).length,
    [profiles, reviewed],
  );

  const watchedItems = profiles.filter((p) => watched.has(p.orgnr)).map((p) => ({ label: nameOf(p), value: p.orgnr }));

  return (
    <div className="overflow-x-clip">
      <WebGLLiquid
        title=""
        subtitle=""
        description=""
        colorDeep="#07152b"
        colorMid="#1b4f8f"
        colorHighlight="#86b4ee"
        speed={reduce ? 0 : 0.45}
        reveal={false}
        grain={0.04}
        className="h-[470px] min-h-0 md:h-[350px] [&>div.z-10]:py-8! md:[&>div.z-10]:py-10!"
      >
        <div>
          <h2 className="m-0 text-[clamp(24px,3.4vw,34px)] leading-[1.15] font-bold tracking-[-0.025em]">
            {profiles.length.toLocaleString("en-GB")} companies, every fact sourced
          </h2>
          <p className="mt-3 mb-0 max-w-[56ch] text-white/85">
            Each value links to the Brønnøysund register page it came from and shows when it was retrieved.
          </p>
          <dl className="m-0 mt-6 flex flex-wrap gap-x-9 gap-y-4">
            <Stat value={profiles.length} label="Profiles" />
            <Stat value={stats.withAccounts} label="With annual accounts" />
            <Stat value={stats.changed} label="Changed since first check" />
            <Stat value={stats.flagged} label="Not active" />
          </dl>
          <p className="mt-5 mb-0 text-[13px] text-white/75">
            {report.requests_made != null
              ? `${report.requests_made.toLocaleString("en-GB")} requests in ${Math.round(report.seconds ?? 0)} seconds. No paid APIs, no model calls.`
              : "No run report was found next to the profiles."}
          </p>
        </div>
      </WebGLLiquid>

      <div className="grid gap-x-10 gap-y-12 px-4 pt-10 pb-20 md:px-[clamp(16px,4vw,56px)] xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <section aria-labelledby="queue-h">
          <h3 id="queue-h" className="mb-1 text-[17px] font-semibold tracking-tight">Review queue</h3>
          <p className="mt-0 mb-4 max-w-[48ch] text-muted">
            Companies that are not active or that changed since the first check. Drag a card into the slot to mark it reviewed.
          </p>
          {queue.length === 0 ? (
            <p className="m-0">Nothing needs review. Every flagged or changed company has been marked reviewed.</p>
          ) : (
            <>
              <Shredder<QueueItem>
                items={queue}
                width={340}
                height={390}
                fallHeight={110}
                slitColor={c.muted}
                color={c.surface}
                onShred={(item) => onReview(item.p.orgnr, true)}
                renderItem={(item) => (
                  <div className="flex h-[56px] flex-col justify-center gap-0.5 rounded-ui border border-line bg-surface px-3.5 text-left text-ink">
                    <span className="flex items-baseline justify-between gap-3">
                      <span className="truncate font-semibold">{nameOf(item.p)}</span>
                      <button
                        type="button"
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={() => onOpen(item.p.orgnr)}
                        className="shrink-0 text-[13px] text-accent underline underline-offset-2"
                      >
                        Open
                      </button>
                    </span>
                    <span className="truncate text-[13px] text-muted">
                      <span className="num">{item.p.orgnr}</span>
                      {"   "}
                      {statusLabel(item.p.status)}
                      {(item.p.history?.length ?? 0) > 0 ? `   ${item.p.history!.length} ${item.p.history!.length === 1 ? "change" : "changes"}` : ""}
                    </span>
                  </div>
                )}
              />
              {queueTotal > queue.length && (
                <p className="mt-3 mb-0 text-[13px] text-muted">
                  Showing {queue.length} of {queueTotal}. The rest appear as you review these.
                </p>
              )}
            </>
          )}
        </section>

        <section aria-labelledby="watch-h">
          <h3 id="watch-h" className="mb-1 text-[17px] font-semibold tracking-tight">Watchlist</h3>
          <p className="mt-0 mb-4 max-w-[48ch] text-muted">
            Watch a company with the bell on its profile, or swipe its row in the list. Open the folder to jump back to it.
          </p>
          <FolderFloat
            items={watchedItems}
            label="Watching"
            sublabel={`${watchedItems.length} ${watchedItems.length === 1 ? "company" : "companies"}`}
            trigger="click"
            physics={!reduce}
            onSelect={(value) => onOpen(value)}
            folderColor={c.accent}
            frontColor={c.accent}
            paperColor={c.surface}
            itemColor={c.surface}
            itemTextColor={c.ink}
            labelColor={c.dark ? "#10151b" : "#f6f9fc"}
          />
        </section>
      </div>
    </div>
  );
}
