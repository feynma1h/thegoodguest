/**
 * The product wordmark — isolated here because NO NAME HAS BEEN CHOSEN.
 * "roomstudio" is a stand-in (see CLAUDE.md "Naming" and decision 0055).
 * The design file renders every wordmark slot as a literal placeholder
 * in quiet tracked mono; this component honors that — deliberately quiet,
 * because the room is the hero.
 *
 * The mark is the room corner: a pointy-top hexagon divided by a three-way
 * seam into two wall faces and a floor — the captured volume, seen at true
 * 30° isometric. Same geometry as the app icon (decision 0176) and the
 * favicon re-exported from it, so a person meets one mark across the phone,
 * the tab and the site.
 *
 * Outline in `currentColor`, floor in the rust accent. The icon's other two
 * surfaces are NOT filled here, and that was measured rather than assumed:
 * filling all three fails twice at this scale. At ~10px on parchment the ink
 * band swallows the interior and the mark reads as a blob; on the room
 * page's dark surface the band is darker than its background, so the
 * hexagon's silhouette disappears and the cream walls glow as a bright
 * shape. The icon can do it because it sits on its own light field. A
 * wordmark has no field. Keeping the outline on `currentColor` is what lets
 * one mark serve both tones; the floor is the one surface that can hold a
 * fixed colour, and it reads on both.
 *
 * Sized at 1em, not larger. The glyph it replaced was a text character and
 * sat under the cap height; a mark set well above it reads as a logo the
 * page is presenting rather than a stand-in it is holding quietly. Judged
 * in the browser at true size in both tones — above 1em the mark dominates
 * the tracked mono, and above stroke 1.8 the seam fills in and the corner
 * stops reading.
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

export default function Wordmark({
  className,
  tone = "ink",
}: {
  className?: string;
  tone?: "ink" | "cream";
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.16em] ${
        tone === "cream" ? "text-paper/70" : "text-ink/70"
      } ${className ?? ""}`}
    >
      <svg
        viewBox="0 0 20 20"
        width="1em"
        height="1em"
        aria-hidden
        focusable="false"
        className="shrink-0"
      >
        {/* The floor first, so the outline and seam sit over its edges. */}
        <path d="M10 10 2.21 14.5 10 19 17.79 14.5Z" className="fill-accent" />
        {/* The volume, then the corner it is seen from: centre to apex is
            where the two walls meet, centre to each lower vertex is where
            each wall meets the floor. */}
        <path
          d="M10 1 17.79 5.5 17.79 14.5 10 19 2.21 14.5 2.21 5.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinejoin="round"
        />
        <path
          d="M10 10 10 1M10 10 2.21 14.5M10 10 17.79 14.5"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
        />
      </svg>
      roomstudio
    </span>
  );
}
