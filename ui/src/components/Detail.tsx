import { useState } from "react";
import { motion, useReducedMotion, type Variants } from "motion/react";
import { HugeiconsIcon } from "@hugeicons/react";
import { LinkSquare02Icon } from "@hugeicons/core-free-icons";
import BellToggle from "@/components/react-bits/BellToggle";
import FuseButton from "@/components/react-bits/FuseButton";
import LineSidebar from "@/components/react-bits/LineSidebar";
import type { Fact, Profile } from "@/types";
import { LABELS, MONEY, SECTIONS, day, nameOf, plain, statusLabel } from "@/lib/format";
import { Amount } from "@/components/Amount";
import { usePalette } from "@/lib/theme";
import { cn } from "@/lib/utils";

const container: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.05 } } };
const item: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: [0.16, 1, 0.3, 1] } },
};

function Source({ fact }: { fact: Fact }) {
  const safe = /^https?:\/\//.test(fact.source_url);
  return (
    <span className="mt-0.5 block text-[12.5px] text-muted">
      {safe ? (
        <a href={fact.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1">
          {fact.source}
          <HugeiconsIcon icon={LinkSquare02Icon} size={12} strokeWidth={2} aria-hidden="true" />
        </a>
      ) : (
        fact.source
      )}
      {`, retrieved ${day(fact.retrieved_at)}`}
      {fact.as_of ? `, refers to ${day(fact.as_of)}` : ""}
    </span>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <motion.section id={id} variants={item} className="mt-9 scroll-mt-20">
      <h3 className="mb-3 text-[17px] font-semibold tracking-tight">{title}</h3>
      {children}
    </motion.section>
  );
}

interface Props {
  p: Profile;
  watched: boolean;
  reviewed: boolean;
  onWatch: (id: string, on: boolean) => void;
  onReview: (id: string, on: boolean) => void;
}

export function Detail({ p, watched, reviewed, onWatch, onReview }: Props) {
  const c = usePalette();
  const reduce = useReducedMotion();
  const onAccent = c.dark ? "#10151b" : "#f6f9fc";
  // Reviewed before this view opened: show it as done. Otherwise offer the undoable button.
  // Read once at mount: if it followed the live value, the button would unmount the moment it commits
  // and the undo window would vanish.
  const [reviewedAtOpen] = useState(reviewed);
  const [reopened, setReopened] = useState(false);
  const showDone = reviewedAtOpen && !reopened;

  const facts = p.facts ?? {};
  const hasFacts = Object.keys(facts).length > 0;
  const history = [...(p.history ?? [])].reverse();
  const money = MONEY.filter(([k]) => facts[k]);
  const first = money.length ? facts[money[0][0]] : null;

  const sections = SECTIONS.map(([title, keys]) => ({ id: `sec-${title.toLowerCase()}`, title, keys: keys.filter((k) => facts[k]) })).filter((s) => s.keys.length);
  const nav = [
    ...sections.map((s) => ({ id: s.id, title: s.title })),
    ...(money.length ? [{ id: "sec-financials", title: "Financials" }] : []),
    { id: "sec-changes", title: "Changes" },
    { id: "sec-matching", title: "Matching" },
  ];
  const jump = (i: number) => {
    document.getElementById(nav[i].id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  };

  return (
    <div className="grid max-w-[1180px] gap-x-8 lg:grid-cols-[minmax(0,1fr)_170px]">
      <motion.article variants={container} initial="hidden" animate="show" className="min-w-0 px-4 pt-8 pb-16 md:pl-[clamp(16px,4vw,56px)]">
        <motion.header variants={item}>
          <h2 className="mb-2 text-[clamp(24px,3.4vw,34px)] leading-[1.15] font-bold tracking-[-0.025em] [overflow-wrap:anywhere]">
            {nameOf(p)}
          </h2>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-muted">
            <span className="num">{p.orgnr}</span>
            <span
              className={cn(
                "rounded-ui border border-ink px-2 py-px text-[13px]",
                p.status !== "active" ? "bg-ink text-bg" : "text-ink",
              )}
            >
              {statusLabel(p.status)}
            </span>
            <span>Checked {day(p.checked_at)}</span>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <BellToggle
              offLabel="Watch"
              onLabel="Watching"
              pressed={watched}
              onChange={(v) => onWatch(p.orgnr, v)}
              size="md"
              radius={8}
              color={c.ink}
              background={c.line}
              onColor={onAccent}
              onBackground={c.accent}
              badge={false}
            />
            {showDone ? (
              <span className="inline-flex items-center gap-3">
                <span className="rounded-ui border border-line px-3 py-2 text-[14px]">Reviewed</span>
                <button
                  type="button"
                  className="text-[14px] text-accent underline underline-offset-2"
                  onClick={() => {
                    setReopened(true);
                    onReview(p.orgnr, false);
                  }}
                >
                  Reopen
                </button>
              </span>
            ) : (
              <FuseButton
                label="Mark reviewed"
                undoLabel="Undo"
                doneLabel="Reviewed"
                commitOn="press"
                settle="stay"
                undoWindow={5000}
                size="md"
                radius={8}
                color={c.ink}
                background={c.line}
                fuseColor={c.accent}
                onCommit={() => onReview(p.orgnr, true)}
                onUndo={() => onReview(p.orgnr, false)}
              />
            )}
          </div>
        </motion.header>

        {!hasFacts && (
          <Section id="sec-nofacts" title="No facts published">
            {p.explanation.map((t, i) => <p key={i} className="my-1">{t}</p>)}
          </Section>
        )}

        {hasFacts &&
          sections.map(({ id, title, keys }) => (
            <Section key={id} id={id} title={title}>
              <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-0.5 md:grid-cols-[minmax(130px,200px)_minmax(0,1fr)] md:gap-y-3.5">
                {keys.map((k) => {
                  const f = facts[k];
                  const text = plain(f.value);
                  return (
                    <div key={k} className="contents">
                      <dt className="text-muted">{LABELS[k] ?? k}</dt>
                      <dd className="m-0 mb-3 [overflow-wrap:anywhere] md:mb-0">
                        {k === "website" && /^https?:\/\//i.test(text) ? (
                          <a href={text} rel="noopener noreferrer">{text}</a>
                        ) : (
                          text
                        )}
                        {f.code && /industry|legal|sector/.test(k) ? ` (${f.code})` : ""}
                        {f.members?.length ? <span className="block text-[12.5px] text-muted">{f.members.join(", ")}</span> : null}
                        <Source fact={f} />
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </Section>
          ))}

        {money.length > 0 && first && (
          <Section id="sec-financials" title="Financials">
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-left text-[13px] font-medium text-muted">
                  <th scope="col" className="py-2 pr-3 font-medium">Measure</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Amount</th>
                  <th scope="col" className="py-2 font-medium">Period ending</th>
                </tr>
              </thead>
              <tbody>
                {money.map(([k, label]) => {
                  const f = facts[k];
                  return (
                    <tr key={k} className="align-top">
                      <td className="py-2 pr-3">{label}</td>
                      <td className="py-2 pr-3 text-right">
                        <Amount value={Number(f.value)} currency={f.currency} />
                      </td>
                      <td className="py-2">{day(f.as_of)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Source fact={first} />
          </Section>
        )}

        <Section id="sec-changes" title="Changes since first check">
          {history.length === 0 ? (
            <p className="m-0">No changes detected. First checked {day(p.first_checked_at ?? p.checked_at)}.</p>
          ) : (
            <ul className="m-0 list-disc pl-5">
              {history.slice(0, 12).map((ch, i) => (
                <li key={i} className="my-1">
                  {day(ch.detected_at)}: {LABELS[ch.field] ?? ch.field} changed from {plain(ch.old)} to {ch.new === null ? "removed" : plain(ch.new)}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section id="sec-matching" title="How this was matched">
          <ul className="m-0 list-disc pl-5">
            {p.explanation.map((t, i) => <li key={i} className="my-1">{t}</li>)}
          </ul>
        </Section>
      </motion.article>

      <nav aria-label="On this profile" className="sticky top-[84px] hidden self-start pt-28 lg:block">
        <LineSidebar
          items={nav.map((n) => n.title)}
          showIndex={false}
          fontSize={0.9}
          accentColor={c.accent}
          textColor={c.muted}
          markerColor={c.line}
          onItemClick={(i) => jump(i)}
        />
      </nav>
    </div>
  );
}
