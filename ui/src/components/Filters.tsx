import { useState, type ReactNode } from "react";
import CodeSlots, { type CodeSlotsStatus } from "@/components/react-bits/CodeSlots";
import GlideSelect from "@/components/react-bits/GlideSelect";
import JellyRadio from "@/components/react-bits/JellyRadio";
import RubberSegment from "@/components/react-bits/RubberSegment";
import SquishSwitch from "@/components/react-bits/SquishSwitch";
import BranchedMenu from "@/components/react-bits/BranchedMenu";
import { usePalette } from "@/lib/theme";
import { statusLabel } from "@/lib/format";

export type SortKey = "name" | "status" | "changes";

export interface JumpResult {
  ok: boolean;
  message: string;
}

interface Props {
  statuses: Record<string, number>;
  total: number;
  forms: { value: string; label: string }[];
  status: string;
  form: string;
  changedOnly: boolean;
  sort: SortKey;
  onStatus: (v: string) => void;
  onForm: (v: string) => void;
  onChanged: (v: boolean) => void;
  onSort: (v: SortKey) => void;
  onJump: (code: string) => JumpResult;
  onExport: (value: string) => void;
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <div className="text-[13px] text-muted">{label}</div>
      {children}
      {hint}
    </div>
  );
}

export function Filters(p: Props) {
  const c = usePalette();
  const onAccent = c.dark ? "#10151b" : "#f6f9fc";
  const [code, setCode] = useState("");
  const [slotStatus, setSlotStatus] = useState<CodeSlotsStatus>("idle");
  const [message, setMessage] = useState("");

  const statusOptions = [
    { value: "all", label: "All statuses", tag: String(p.total) },
    ...Object.keys(p.statuses).sort().map((s) => ({ value: s, label: statusLabel(s), tag: String(p.statuses[s]) })),
  ];

  return (
    <div className="grid gap-5 border-b border-line px-4 pt-1 pb-5">
      <Field
        label="Jump to an organisation number"
        hint={
          <p className="m-0 min-h-5 text-[13px]" role="status" aria-live="polite" style={{ color: slotStatus === "error" ? c.ink : c.muted }}>
            {message || "Type nine digits. The check digit is verified before looking it up."}
          </p>
        }
      >
        <CodeSlots
          length={9}
          value={code}
          onChange={(v) => {
            const digits = v.replace(/\D/g, "");
            setCode(digits);
            // CodeSlots clears its own digits after an error. Keep the message until the user types again.
            if (digits.length > 0) {
              if (slotStatus !== "idle") setSlotStatus("idle");
              if (message) setMessage("");
            }
          }}
          onComplete={(v) => {
            const r = p.onJump(v);
            setSlotStatus(r.ok ? "success" : "error");
            setMessage(r.message);
          }}
          status={slotStatus}
          slotSize={30}
          gap={4}
          radius={6}
          accentColor={c.accent}
          inkColor={c.ink}
          slotColor={c.bg}
          digitColor={c.ink}
          dangerColor={c.dark ? "#ff8a8a" : "#b3261e"}
          ariaLabel="Organisation number, nine digits"
        />
      </Field>

      <Field label="Status">
        <GlideSelect
          options={statusOptions}
          value={p.status || "all"}
          onChange={(v) => p.onStatus(v === "all" ? "" : v)}
          showTags
          size="md"
          radius={6}
          menuWidth={260}
          accentColor={c.accent}
          surfaceColor={c.bg}
          highlightColor={c.line}
          textColor={c.ink}
          ariaLabel="Filter by status"
        />
      </Field>

      {p.forms.length > 1 && (
        <Field label="Legal form">
          <JellyRadio
            items={p.forms}
            value={p.form || "all"}
            onChange={(v) => p.onForm(v === "all" ? "" : v)}
            size="sm"
            radius={6}
            chipColor={c.line}
            activeColor={c.accent}
            textColor={c.ink}
            activeTextColor={onAccent}
            ariaLabel="Filter by legal form"
          />
        </Field>
      )}

      <Field label="Show only">
        <SquishSwitch
          checked={p.changedOnly}
          onChange={p.onChanged}
          label="Profiles that changed since first check"
          trackColor={c.line}
          trackOnColor={c.accent}
          thumbColor={c.surface}
          thumbOnColor={c.surface}
        />
      </Field>

      <Field label="Sort by">
        <RubberSegment
          items={[
            { value: "name", label: "Name" },
            { value: "status", label: "Status" },
            { value: "changes", label: "Changes" },
          ]}
          value={p.sort}
          onChange={(v) => p.onSort(v as SortKey)}
          size="sm"
          radius={6}
          trackColor={c.line}
          thumbColor={c.accent}
          textColor={c.ink}
          activeTextColor={onAccent}
          aria-label="Sort the list"
        />
      </Field>

      <Field label="Export">
        <BranchedMenu
          items={[
            {
              label: "This company",
              children: [
                { value: "profile-json", label: "Profile as JSON" },
                { value: "copy-orgnr", label: "Copy organisation number" },
              ],
            },
            {
              label: "Companies in the list",
              children: [
                { value: "list-jsonl", label: "JSON lines" },
                { value: "list-csv", label: "CSV summary" },
              ],
            },
            { label: "Run report", children: [{ value: "report-json", label: "run_report.json" }] },
          ]}
          onSelect={(v) => p.onExport(v)}
          color={c.ink}
          accentColor={c.accent}
          lineColor={c.muted}
          width={300}
          fontSize={14}
        />
      </Field>
    </div>
  );
}
