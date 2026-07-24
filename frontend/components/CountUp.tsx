"use client";

import { useEffect, useRef, useState } from "react";
import { useInView, useReducedMotion } from "motion/react";

/**
 * Counts up to a value when it scrolls into view. Honors reduced motion by
 * showing the final number immediately — a count-up is decorative, so it must
 * never withhold information from someone who has asked for stillness.
 */
export function CountUp({
  value,
  format = (n) => Math.round(n).toLocaleString("en-US"),
  duration = 1100,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-10%" });
  const [display, setDisplay] = useState(value);

  useEffect(() => {
    if (reduce || !inView) {
      setDisplay(value);
      return;
    }
    let raf = 0;
    let start = 0;
    const step = (ts: number) => {
      if (!start) start = ts;
      const p = Math.min((ts - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      setDisplay(value * eased);
      if (p < 1) raf = requestAnimationFrame(step);
      else setDisplay(value);
    };
    // Start from zero only when we're actually animating.
    setDisplay(0);
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [inView, value, duration, reduce]);

  // The animating number is decorative and hidden from assistive tech; a
  // visually-hidden sibling carries the real final value. (aria-label on a bare
  // span is a role=generic naming violation that axe flags and some AT ignore.)
  return (
    <span ref={ref}>
      <span aria-hidden="true">{format(display)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  );
}
