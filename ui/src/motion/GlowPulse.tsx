import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface GlowPulseProps {
  children: ReactNode;
  color?: string;
  className?: string;
}

/**
 * Pulsing glow halo around children. Use to draw attention (active agent card,
 * incoming notification). Takes colour as CSS var string, defaults to cyan.
 */
export function GlowPulse({ children, color = "var(--j-cyan-glow)", className }: GlowPulseProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <motion.div
      data-motion="glow-pulse"
      className={className}
      style={{ position: "relative" }}
      animate={
        reduce
          ? undefined
          : {
              boxShadow: [
                `0 0 0 0 ${color}`,
                `0 0 0 12px transparent`,
              ],
            }
      }
      transition={reduce ? undefined : { duration: 2, repeat: Infinity, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
