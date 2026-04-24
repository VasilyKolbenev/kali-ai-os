import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { motion as motionTokens } from "../tokens";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface FadeSlideUpProps {
  children: ReactNode;
  delay?: number;
  className?: string;
}

export function FadeSlideUp({ children, delay = 0, className }: FadeSlideUpProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <motion.div
      data-motion="fade-slide-up"
      className={className}
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduce ? 0 : motionTokens.durationBase / 1000,
        ease: motionTokens.easeOut,
        delay,
      }}
    >
      {children}
    </motion.div>
  );
}
