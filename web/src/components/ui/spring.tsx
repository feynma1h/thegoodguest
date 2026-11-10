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

/* Pill actions (decision 0361): an ink fill for the primary act on the
 * daylight ground, a hairline ring for the alternative, and the same pair
 * reversed on dusk. Terracotta never fills a button; it belongs to the mark.
 * The `cream` names are kept for their call sites: they are the dusk pair. */
const PILL_VARIANTS = {
  primary:
    "rounded-full bg-ink px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#2a3644]",
  ghost:
    "rounded-full px-6 py-2.5 text-sm font-semibold text-ink ring-1 ring-inset ring-ink/20 hover:ring-ink/45",
  quiet:
    "rounded-full px-6 py-2.5 text-sm font-medium text-ink-2 ring-1 ring-inset ring-ink/15 hover:text-ink hover:ring-ink/35",
  cream:
    "rounded-full bg-on-dusk px-6 py-2.5 text-sm font-semibold text-dusk hover:bg-white",
  creamGhost:
    "rounded-full px-6 py-2.5 text-sm font-semibold text-on-dusk ring-1 ring-inset ring-on-dusk/25 hover:ring-on-dusk/50",
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
