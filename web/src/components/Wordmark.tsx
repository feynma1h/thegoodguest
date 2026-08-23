/**
 * The product wordmark — isolated here because NO NAME HAS BEEN CHOSEN.
 * The product name is "The Good Guest" (decision 0245). This file and
 * DesignSystem/Wordmark.swift are still the only places it is set.
 * The design file renders every wordmark slot as a literal placeholder
 * in quiet tracked mono; this component honors that — deliberately quiet,
 * because the room is the hero.
 *
 * The mark is the room corner: a pointy-top hexagon divided by a three-way
 * seam into two wall faces and a floor — the captured volume, seen at true
 * 30° isometric. Its geometry is NOT authored here. It comes from
 * `markGeometry.ts`, which `tools/gen_mark.py` generates from the one source
 * every surface is cut from — the app icon, the tab icon, this wordmark and
 * the share card. To change the mark, change the generator and re-run it;
 * editing the paths here would fork it again.
 *
 * The face colours are absolute and do NOT inherit `currentColor`. The mark
 * carries its own cream and its own rust onto whatever it sits on, which is
 * what lets it stay the same object on the phone icon, the browser tab and
 * both of this site's surfaces. A mark whose interior is the page showing
 * through is a different mark on every page.
 *
 * `tone` picks which of the two ink plates the mark sits on, and that is the
 * only thing that varies:
 *
 *   ink   → on parchment; the framed plate, whose rim band separates the
 *           mark from a light field.
 *   cream → on the room page's ink surface; the frameless plate, which
 *           circumscribes the three faces exactly so only the seams read.
 *           Decision 0176 measured why: a full band on a dark field sits
 *           0.11 off it and reads as a heavy ring rather than a drawn edge.
 *
 * Sized against the cap height of the tracked mono beside it rather than at
 * a round em: the mark is a filled object where the surrounding text is a
 * thin uppercase rule, so matching em would leave it reading as the larger
 * of the two. Judged in the browser at true size in both tones.
 *
 * This is the only place the name is RENDERED AS THE MARK, but it is not the
 * only place the string appears in user-visible text. When the real name
 * lands, also update: app/layout.tsx (the tab title), and app/terms/page.tsx
 * and app/privacy/page.tsx (titles, descriptions, and body copy, including the
 * "working title" sentence in Terms §2, which stops being true). The
 * "roomstudio:"-prefixed localStorage keys in app/page.tsx, lib/seen.ts, and
 * components/NewRoomSheet.tsx are internal and can stay — renaming them
 * silently resets returning visitors.
 */

import {
  FACES,
  MARK_FLOOR,
  MARK_INK,
  MARK_WALL,
  PLATE_FRAMED,
  PLATE_FRAMELESS,
} from "@/components/markGeometry";

/**
 * The mark on its own, at the given size. Exported for surfaces that show the
 * mark without the name beside it.
 */
export function Mark({
  size = "1em",
  onDark = false,
  className,
}: {
  size?: string;
  onDark?: boolean;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 1024 1024"
      width={size}
      height={size}
      aria-hidden
      focusable="false"
      className={`shrink-0 ${className ?? ""}`}
    >
      <path d={onDark ? PLATE_FRAMELESS : PLATE_FRAMED} fill={MARK_INK} />
      <path d={FACES[0]} fill={MARK_WALL} />
      <path d={FACES[1]} fill={MARK_WALL} />
      <path d={FACES[2]} fill={MARK_FLOOR} />
    </svg>
  );
}

export default function Wordmark({
  className,
  tone = "ink",
}: {
  className?: string;
  tone?: "ink" | "cream";
}) {
  return (
    <span
      className={`inline-flex items-center gap-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.16em] ${
        tone === "cream" ? "text-paper/70" : "text-ink/70"
      } ${className ?? ""}`}
    >
      <Mark size="13px" onDark={tone === "cream"} />
      The Good Guest
    </span>
  );
}
