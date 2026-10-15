import { useRef } from "react";
import { useInView, useReducedMotion } from "motion/react";
import CountUp from "@/components/react-bits/CountUp";

/** A whole number. The true value is always the default. Only after it scrolls into view
 *  does it count up (React Bits CountUp), so it never shows a starting value to anything
 *  that does not scroll (print, screenshots, reduced motion). Screen readers get the final value. */
export function Counted({ value, className }: { value: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduce = useReducedMotion();
  const inView = useInView(ref, { once: true });
  const final = value.toLocaleString("en-GB");
  return (
    <span ref={ref} className={className}>
      {inView && !reduce ? (
        <>
          <span aria-hidden="true">
            <CountUp to={value} duration={1} separator="," />
          </span>
          <span className="sr-only">{final}</span>
        </>
      ) : (
        final
      )}
    </span>
  );
}
