import type { FactValue, Profile } from "@/types";

export const LABELS: Record<string, string> = {
  legal_form: "Legal form",
  registered_in_enhetsregisteret: "Registered",
  founded: "Founded",
  business_address: "Business address",
  municipality: "Municipality",
  postal_address: "Postal address",
  industry_1: "Main industry",
  industry_2: "Industry 2",
  industry_3: "Industry 3",
  employees: "Employees",
  institutional_sector: "Sector",
  vat_registered: "VAT registered",
  in_business_register: "In Register of Business Enterprises",
  website: "Website",
  email: "Email",
  phone: "Phone",
  stated_purpose: "Stated purpose",
  stated_activity: "Activity",
  parent_organisation: "Parent unit",
  sub_units: "Sub-units",
  last_filed_accounts_year: "Latest filed accounts",
  ceo: "CEO",
  board_chair: "Board chair",
  board_size: "Board members",
  auditor: "Auditor",
  accountant: "Accountant",
  bankruptcy_date: "Bankruptcy date",
  liquidation_start: "Liquidation started",
  closed_on: "Closed",
  deleted_on: "Removed from register",
  name: "Name",
  revenue: "Operating revenue",
  operating_result: "Operating result",
  net_result: "Net result",
  total_assets: "Total assets",
  equity: "Equity",
};

export const SECTIONS: [string, string[]][] = [
  ["Identity", ["legal_form", "registered_in_enhetsregisteret", "founded", "bankruptcy_date", "liquidation_start", "closed_on", "deleted_on", "parent_organisation", "sub_units"]],
  ["Location", ["business_address", "municipality", "postal_address"]],
  ["Business", ["industry_1", "industry_2", "industry_3", "employees", "institutional_sector", "vat_registered", "in_business_register", "stated_purpose", "stated_activity", "website", "email", "phone"]],
  ["People", ["ceo", "board_chair", "board_size", "auditor", "accountant"]],
];

export const MONEY: [string, string][] = [
  ["revenue", "Operating revenue"],
  ["operating_result", "Operating result"],
  ["net_result", "Net result"],
  ["total_assets", "Total assets"],
  ["equity", "Equity"],
];

export function day(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function plain(v: FactValue | null): string {
  if (v === null) return "none";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.join(", ");
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(v))) return day(String(v));
  return String(v);
}

export function money(v: number): string {
  return new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 })
    .format(v)
    .replace(/−/g, "-");
}

export function nameOf(p: Profile): string {
  const n = p.facts?.name?.value;
  return typeof n === "string" && n ? n : `Unnamed (${p.orgnr})`;
}

export function statusLabel(s: string): string {
  return s.replace(/_/g, " ");
}
