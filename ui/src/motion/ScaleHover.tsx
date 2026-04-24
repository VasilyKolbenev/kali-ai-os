import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface ScaleHoverProps {
  children: ReactNode;
  scale?: number;
  className?: string;
  onClick?: () => void;
}

export function ScaleHover({ children, scale = 1.02, className, onClick }: ScaleHoverProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <motion.div
      data-motion="scale-hover"
      className={className}
      onClick={onClick}
      whileHover={reduce ? undefined : { scale }}
      whileTap={reduce ? undefined : { scale: 0.98 }}
      transition={{ duration: 0.15, ease: [0.2, 0.8, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}
