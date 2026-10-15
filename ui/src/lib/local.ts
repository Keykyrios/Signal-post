import { useCallback, useEffect, useState } from "react";

/** A set of ids kept in localStorage. Storage can throw or come back empty
 *  (private windows, blocked storage), so every access is wrapped and the UI
 *  still works from memory when it fails. */
export function useStoredSet(key: string) {
  const [items, setItems] = useState<Set<string>>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : []);
    } catch {
      return new Set();
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify([...items]));
    } catch {
      /* memory only */
    }
  }, [key, items]);

  const set = useCallback((id: string, on: boolean) => {
    setItems((prev) => {
      if (prev.has(id) === on) return prev;
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  return [items, set] as const;
}
