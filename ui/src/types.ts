export type FactValue = string | number | boolean | string[];

export interface Fact {
  value: FactValue;
  source: string;
  source_url: string;
  retrieved_at: string;
  as_of?: string;
  code?: string;
  currency?: string;
  members?: string[];
  first_seen?: string;
  last_changed?: string;
}

export interface Change {
  field: string;
  old: FactValue | null;
  new: FactValue | null;
  detected_at: string;
  note?: string;
}

export interface Profile {
  orgnr: string;
  status: string;
  checked_at: string;
  first_checked_at?: string;
  kind?: string;
  facts: Record<string, Fact>;
  changes: Change[];
  history?: Change[];
  explanation: string[];
}

export interface RunReport {
  finished_at?: string;
  profiles_written?: number;
  requests_made?: number;
  seconds?: number;
  external_api_cost_usd?: number;
  model_calls?: number;
}
