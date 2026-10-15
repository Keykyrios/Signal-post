// Same modulus-11 check as signalpost/orgnr.py, so the UI and the agent agree.
const WEIGHTS = [3, 2, 7, 6, 5, 4, 3, 2];

export function normalize(raw: string): string {
  return String(raw ?? "").replace(/\D/g, "");
}

export function isValid(raw: string): boolean {
  const d = normalize(raw);
  if (d.length !== 9) return false;
  const total = WEIGHTS.reduce((sum, w, i) => sum + w * Number(d[i]), 0);
  let check = 11 - (total % 11);
  if (check === 11) check = 0;
  if (check === 10) return false;
  return check === Number(d[8]);
}
