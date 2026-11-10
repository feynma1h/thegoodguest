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
 * components/ui/Dialog.tsx fade in on short eased tweens, because a spring
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
 * The one exception is `danger`, the deep terracotta reserved for the single
 * irreversible act the product offers (deleting an account).
 * The `cream` names are kept for their call sites: they are the dusk pair. */
const PILL_VARIANTS = {
  primary: "bg-ink font-semibold text-white hover:bg-[#2a3644]",
  ghost: "font-semibold text-ink ring-1 ring-inset ring-ink/20 hover:ring-ink/45",
  quiet:
    "font-medium text-ink-2 ring-1 ring-inset ring-ink/15 hover:text-ink hover:ring-ink/35",
  cream: "bg-on-dusk font-semibold text-dusk hover:bg-white",
  creamGhost:
    "font-semibold text-on-dusk ring-1 ring-inset ring-on-dusk/25 hover:ring-on-dusk/50",
  danger: "bg-accent-deep font-semibold text-white hover:bg-[#8f392d]",
} as const;

/** `md` is the nav's and the sheets' pill; `lg` is a page's main action. */
const PILL_SIZES = {
  md: "min-h-10 px-6 py-2.5 text-sm",
  lg: "h-[52px] px-[26px] text-base",
} as const;

type PillVariant = keyof typeof PILL_VARIANTS;
type PillSize = keyof typeof PILL_SIZES;

const pillClass = (variant: PillVariant, size: PillSize, extra?: string) =>
  `inline-flex items-center justify-center gap-2.5 whitespace-nowrap rounded-full transition-colors ${PILL_SIZES[size]} ${PILL_VARIANTS[variant]} ${extra ?? ""}`;

/** The arrow a forward-moving action carries. */
export function ArrowIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h14" />
      <path d="M13 6l6 6-6 6" />
    </svg>
  );
}

/** A pill CTA with the standard spring press/hover behavior. */
export function PillLink({
  href,
  variant = "primary",
  size = "md",
  className,
  children,
}: {
  href: string;
  variant?: PillVariant;
  size?: PillSize;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <MotionLink
      href={href}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      transition={SPRING}
      className={pillClass(variant, size, className)}
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
  size = "md",
  disabled = false,
  className,
  children,
}: {
  onClick: () => void;
  variant?: PillVariant;
  size?: PillSize;
  disabled?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      whileHover={disabled ? undefined : { scale: 1.02 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      transition={SPRING}
      className={pillClass(
        variant,
        size,
        `cursor-pointer disabled:cursor-default disabled:opacity-60 ${className ?? ""}`,
      )}
    >
      {children}
    </motion.button>
  );
}
