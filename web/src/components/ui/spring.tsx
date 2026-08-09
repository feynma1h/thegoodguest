"use client";

/**
 * The motion system: ONE damped spring for anything that MOVES — hover, press,
 * layout shifts (founding draft: tension 180 / friction 24, motion's
 * stiffness/damping equivalents). Nothing animates that doesn't need to, and
 * anything that travels uses exactly this. Import SPRING; don't hand-tune a
 * second one.
 *
 * Two deliberate exceptions, both of which are entrances rather than motion:
 * the room-card stagger in app/rooms/page.tsx and the sheet scrim in
 * components/NewRoomSheet.tsx fade in on short eased tweens, because a spring
 * on an appearing element overshoots opacity for no gain.
 *
 * The 3D reveal is a separate system on purpose — lib/reveal.ts scores the
 * whole choreography on smootherstep and SplatViewer plays it. Same intent
 * (begin and arrive at rest), different medium; it does not import SPRING.
 */

import Link from "next/link";
import { motion, type Transition } from "motion/react";

export const SPRING: Transition = { type: "spring", stiffness: 180, damping: 24 };

export const MotionLink = motion.create(Link);

/* Pill actions per the Good Guest system: rust fill for the primary act,
 * quiet ink outline for the alternative, cream fill on dark panels. */
const PILL_VARIANTS = {
  primary:
    "rounded-full bg-accent px-6 py-2.5 text-sm font-semibold text-paper hover:bg-accent-deep",
  ghost:
    "rounded-full border-[1.5px] border-ink/35 px-6 py-2.5 text-sm font-medium text-ink hover:border-ink/60",
  quiet:
    "rounded-full border-[1.5px] border-ink/20 px-6 py-2.5 text-sm font-medium text-ink/60 hover:border-ink/40 hover:text-ink",
  cream:
    "rounded-full bg-paper px-6 py-2.5 text-sm font-semibold text-ink hover:bg-white",
  creamGhost:
    "rounded-full border-[1.5px] border-paper/35 px-6 py-2.5 text-sm font-medium text-paper/85 hover:border-paper/60 hover:text-paper",
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
