import { useRef } from "react";
import { useInView, useReducedMotion } from "motion/react";
import CountUp from "@/components/react-bits/CountUp";
import { money } from "@/lib/format";

/** A money amount. The real figure is always the default. Only once the figure
 *  scrolls into view does it count up, so the eye lands on it. Without that
 *  trigger (below the fold, printing, screenshots, reduced motion) the true
 *  value is shown, never a starting value. Screen readers get the final value only. */
export function Amount({ value, currency }: { value: number; currency?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduce = useReducedMotion();
  const inView = useInView(ref, { once: true });
  const final = money(value);
  const animate = inView && !reduce;
  return (
    <span ref={ref} className="num whitespace-nowrap">
      {animate ? (
        <>
          <span aria-hidden="true">
            <CountUp to={value} duration={1.1} separator={" "} />
          </span>
          <span className="sr-only">{final}</span>
        </>
      ) : (
        final
      )}
      {currency ? ` ${currency}` : ""}
    </span>
  );
}
