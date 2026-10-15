import type { Profile } from "@/types";
import { nameOf } from "@/lib/format";

export function download(filename: string, text: string, mime: string) {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function cell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  // Quote anything with a delimiter, quote or newline. Also defuse spreadsheet formulas.
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

const COLUMNS = [
  "orgnr", "name", "status", "legal_form", "municipality", "industry", "employees", "ceo",
  "revenue", "revenue_period_end", "currency", "checked_at", "source_url",
] as const;

export function profilesToCsv(list: Profile[]): string {
  const rows = list.map((p) => {
    const f = p.facts ?? {};
    const v = (k: string) => f[k]?.value;
    return [
      p.orgnr, nameOf(p), p.status, v("legal_form"), v("municipality"), v("industry_1"), v("employees"),
      v("ceo"), v("revenue"), f.revenue?.as_of, f.revenue?.currency, p.checked_at, f.name?.source_url,
    ];
  });
  return [COLUMNS.join(","), ...rows.map((r) => r.map(cell).join(","))].join("\n") + "\n";
}

export function profilesToJsonl(list: Profile[]): string {
  return list.map((p) => JSON.stringify(p)).join("\n") + "\n";
}
