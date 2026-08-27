/**
 * The brand on the web: the mark, the name, and the rule that keeps them apart.
 *
 * THE RULE. The mark IS the "oo" of "the good guest" — the same two loops the
 * script draws in the middle of "good", compacted and tilted. So the mark and
 * the name are NEVER set side by side: a lockup of the two would print the same
 * two letters twice, once as a drawing and once as a word. Every surface picks
 * one. Chrome — this site's header, the room page, the iOS app — takes the mark
 * alone, because it is a signature for someone already inside. The artifacts
 * that leave the browser and reach a stranger — the calling card, the share
 * card — take the script wordmark alone, because a stranger needs the name.
 *
 * The only place both appear is the iOS splash, where they appear in SEQUENCE:
 * the name resolves into the mark, which is the rule stated as a motion rather
 * than broken.
 *
 * The mark's geometry is NOT authored here. It comes from `markGeometry.ts`,
 * which `tools/gen_mark.py` generates from the one source every surface is cut
 * from — the app icons, the tab icon, this component and the share cards. To
 * change the mark, change the generator and re-run it; editing the paths here
 * would fork it again.
 *
 * Each ring MUST be filled even-odd. Fill it nonzero and the interior stops
 * being a hole, the two rings become two solid blobs, and the interlock — the
 * only thing that makes this a mark rather than an ellipse — is gone.
 *
 * The colours are absolute and do NOT inherit `currentColor`. The mark carries
 * its own terracotta onto whatever it sits on, which is what lets it stay the
 * same object on the phone icon, the browser tab and both of this site's
 * surfaces. A mark whose interior is the page showing through is a different
 * mark on every page.
 *
 * `tone` picks the ink, and that is the only thing that varies:
 *
 *   ink     → terracotta, for the cream chrome. The mark as drawn.
 *   reverse → cream, for the room page's dark ink surface, matching what the
 *             tab icon does in a dark UA. The dark APP icon deliberately keeps
 *             terracotta instead: it is large enough to carry 3.11:1, where
 *             chrome at 20px is not.
 *
 * The name is a string in exactly one more place on the web — `lib/card/
 * layout.ts`, which cannot import from a component because the card is painted
 * to a canvas by code with no React in it. That copy imports BRAND_NAME from
 * here rather than retyping it.
 *
 * The "roomstudio:"-prefixed localStorage keys in app/page.tsx, lib/seen.ts and
 * components/NewRoomSheet.tsx are identifiers, not presentation, and stay —
 * renaming them silently resets returning visitors.
 */

import {
  MARK_ASPECT,
  MARK_INK,
  MARK_REVERSE,
  MARK_RINGS,
  MARK_VIEWBOX,
} from "@/components/markGeometry";
import {
  WORDMARK_ASPECT,
  WORDMARK_RINGS,
  WORDMARK_SCRIPT,
  WORDMARK_VIEWBOX,
} from "@/components/wordmarkGeometry";

/** The product name. The one-file swap for the name on the web. */
export const BRAND_NAME = "The Good Guest";

export type MarkTone = "ink" | "reverse";

/**
 * The mark, at the given ink HEIGHT. The whole of the brand in chrome — never
 * with the name beside it.
 *
 * Sized by height rather than by a square box: the mark is 1.72 times wider
 * than it is tall, so a square would be 48% empty and every caller would be
 * picking a number that means nothing. The design file's floor is height ≥ 20px
 * — below that the ring band falls under 1.5px and greys out.
 */
export function Mark({
  height = "1em",
  tone = "ink",
  className,
}: {
  height?: string;
  tone?: MarkTone;
  className?: string;
}) {
  const fill = tone === "reverse" ? MARK_REVERSE : MARK_INK;
  return (
    <svg
      viewBox={MARK_VIEWBOX}
      height={height}
      style={{ aspectRatio: MARK_ASPECT }}
      role="img"
      aria-label={BRAND_NAME}
      focusable="false"
      className={`shrink-0 ${className ?? ""}`}
    >
      {MARK_RINGS.map((d) => (
        <path key={d} d={d} fillRule="evenodd" fill={fill} />
      ))}
    </svg>
  );
}

/**
 * The name as artwork, at the given HEIGHT. For the artifacts that leave this
 * site and reach someone who does not know the product — never in chrome, and
 * never beside the mark.
 *
 * Mind the floor. The script's x-height is only 16% of its box, because the
 * loops run so far above and below it, so a wordmark set at 20px has an
 * x-height of 3.3px and is illegible. The design file's minimum is an x-height
 * of 8px, which puts the floor at a height of ~50px — about two and a half
 * times what you would guess. This is the reason chrome takes the mark.
 */
export function Wordmark({
  height = "3em",
  tone = "ink",
  className,
}: {
  height?: string;
  tone?: MarkTone;
  className?: string;
}) {
  const fill = tone === "reverse" ? MARK_REVERSE : MARK_INK;
  return (
    <svg
      viewBox={WORDMARK_VIEWBOX}
      height={height}
      style={{ aspectRatio: WORDMARK_ASPECT }}
      role="img"
      aria-label={BRAND_NAME}
      focusable="false"
      className={`shrink-0 ${className ?? ""}`}
    >
      <path d={WORDMARK_SCRIPT} fillRule="evenodd" fill={fill} />
      {WORDMARK_RINGS.map((d) => (
        <path key={d} d={d} fillRule="evenodd" fill={fill} />
      ))}
    </svg>
  );
}
