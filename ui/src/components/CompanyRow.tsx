import { useRef, type MouseEvent } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Notification03Icon, Tick02Icon } from "@hugeicons/core-free-icons";
import SwipeRow from "@/components/react-bits/SwipeRow";
import type { Profile } from "@/types";
import { nameOf, statusLabel } from "@/lib/format";
import { usePalette } from "@/lib/theme";

interface Props {
  p: Profile;
  selected: boolean;
  watched: boolean;
  reviewed: boolean;
  onSelect: (p: Profile) => void;
  onWatch: (id: string, on: boolean) => void;
  onReview: (id: string, on: boolean) => void;
}

/** One list row. Swipe left (or focus the row and press the left arrow) to reveal
 *  Watch and Reviewed. Clicking or pressing Enter opens the profile. */
export function CompanyRow({ p, selected, watched, reviewed, onSelect, onWatch, onReview }: Props) {
  const c = usePalette();
  const start = useRef<[number, number]>([0, 0]);
  const changes = p.history?.length ?? 0;

  const click = (e: MouseEvent<HTMLDivElement>) => {
    const t = e.target as HTMLElement;
    if (!t.closest("[data-swipe-surface]") || t.closest("[data-swipe-toggle]")) return;
    const keyboard = e.detail === 0;
    const moved = Math.hypot(e.clientX - start.current[0], e.clientY - start.current[1]) > 6;
    if (!keyboard && moved) return;
    onSelect(p);
  };

  return (
    <div
      onPointerDownCapture={(e) => { start.current = [e.clientX, e.clientY]; }}
      onClick={click}
      className="relative"
      data-orgnr={p.orgnr}
    >
      {selected && <span className="pointer-events-none absolute inset-y-0 left-0 z-10 w-[3px] bg-accent" aria-hidden="true" />}
      <SwipeRow
        label={nameOf(p)}
        height={64}
        radius={0}
        actionWidth={88}
        fullSwipe={false}
        haptic={false}
        rowColor={selected ? c.bg : c.surface}
        textColor={c.ink}
        drawerColor={c.line}
        actionColor={c.action}
        actions={[
          {
            id: "watch",
            label: watched ? "Unwatch" : "Watch",
            icon: <HugeiconsIcon icon={Notification03Icon} size={18} strokeWidth={1.8} />,
            onSelect: () => onWatch(p.orgnr, !watched),
          },
          {
            id: "review",
            label: reviewed ? "Reopen" : "Reviewed",
            icon: <HugeiconsIcon icon={Tick02Icon} size={18} strokeWidth={1.8} />,
            onSelect: () => onReview(p.orgnr, !reviewed),
          },
        ]}
      >
        <button type="button" aria-current={selected ? "true" : undefined} className="grid min-w-0 flex-1 gap-0.5 bg-transparent p-0 text-left text-inherit [font:inherit]">
          <span className="truncate font-semibold">{nameOf(p)}</span>
          <span className="truncate text-[13px] text-muted">
            <span className="num">{p.orgnr}</span>
            {"   "}
            {statusLabel(p.status)}
            {changes > 0 ? `   ${changes} ${changes === 1 ? "change" : "changes"}` : ""}
            {watched ? "   watching" : ""}
            {reviewed ? "   reviewed" : ""}
          </span>
        </button>
      </SwipeRow>
    </div>
  );
}
