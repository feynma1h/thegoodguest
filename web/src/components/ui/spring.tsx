"use client";

/**
 * The motion system: ONE damped spring, used by every element that moves
 * (founding draft: tension 180 / friction 24 — motion's stiffness/damping
 * equivalents). Nothing animates that doesn't need to; what does animate
 * uses exactly this.
 */

import Link from "next/link";
import { motion, type Transition } from "motion/react";

export const SPRING: Transition = { type: "spring", stiffness: 180, damping: 24 };

export const MotionLink = motion.create(Link);

const PILL_VARIANTS = {
  primary:
    "rounded-full bg-white px-6 py-2.5 text-sm font-medium text-black hover:bg-zinc-200",
  ghost:
    "rounded-full border border-white/15 px-6 py-2.5 text-sm text-zinc-300 hover:border-white/30 hover:text-white",
} as const;

/** A pill CTA with the standard spring press/hover behavior. */
export function PillLink({
  href,
  variant = "primary",
  className,
  children,
}: {
  href: string;
  variant?: keyof typeof PILL_VARIANTS;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <MotionLink
      href={href}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      transition={SPRING}
      className={`inline-block transition-colors ${PILL_VARIANTS[variant]} ${className ?? ""}`}
    >
      {children}
    </MotionLink>
  );
}

/** Same pill, as a button — for actions that open in place (sheets, menus)
 * rather than navigate. */
export function PillButton({
  onClick,
  variant = "primary",
  className,
  children,
}: {
  onClick: () => void;
  variant?: keyof typeof PILL_VARIANTS;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      transition={SPRING}
      className={`inline-block cursor-pointer transition-colors ${PILL_VARIANTS[variant]} ${className ?? ""}`}
    >
      {children}
    </motion.button>
  );
}
