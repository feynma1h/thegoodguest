"use client";

/**
 * The calling card: an artifact a person makes from their own room and
 * carries away. Rung 0 of the sharing ladder (docs/product/social-layer.md
 * §6) — the measured contour, the derived date title, and a dimension, a
 * count and a measured colour.
 *
 * Nothing leaves our systems. The card is a pure function of the manifest
 * and shell the room page already fetched, drawn in the person's own
 * browser and downloaded by them. There is no route that could serve it to
 * anyone else, which is how §1's invariant is held here — structurally,
 * rather than by promise.
 *
 * The preview IS the file. It is one canvas, painted once; the download is
 * `toBlob` of that same canvas, so what a person approves is what travels.
 *
 * THE NAME IS NOT SETTLED. "Calling card" is a working name — the
 * operator's call, and the product's own name is still a placeholder too.
 * Every user-visible string for this feature is in COPY below, which is
 * this feature's equivalent of the one-file seam in components/Wordmark.tsx.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { CloseButton, Dialog, SheetTitle } from "@/components/ui/Dialog";
import { PillButton } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import type { SceneManifest, ShellDoc } from "@/lib/api/types";
import { cardEligibility, type CardRefusal } from "@/lib/card/eligibility";
import {
  layoutCard,
  type CardLayout,
  type CardVariant,
} from "@/lib/card/layout";
import { measureRoom } from "@/lib/card/measure";
import {
  cardFileName,
  ensureCardFonts,
  paintCard,
  resolveFonts,
} from "@/lib/card/paint";
import { roomTitle } from "@/lib/voice";

/** Every user-visible string this feature owns. The artifact's name is the
 * operator's and is still open; change it here and nowhere else. */
const COPY = {
  open: "Make a card",
  heading: "A card for this room",
  /** §9's obligation: the flow says what is about to be visible. At rung 0
   * the honest answer is short, and it includes what a floor plan with true
   * dimensions does disclose (§3.2). */
  discloses:
    "It carries the room's shape and three of its measurements. No photographs, none of your things, and nothing that points back to your account — a floor plan and its dimensions, and that is all.",
  download: "Download the card",
  frameLandscape: "Wide",
  frameSquare: "Square",
} as const;

/** The refusals, in the guest's register: the real reason and the real
 * remedy, never a shrug. */
function refusalLine(reason: CardRefusal): string {
  switch (reason) {
    case "pre_suppression":
      // Privacy Policy §8 already tells people this; decision 0089 is why.
      return "I can’t make a card for this room. It was scanned before I learned to leave people out of a measurement, so I can’t promise its walls were measured from the room alone — and a card is nothing but those measurements. A fresh scan would settle it.";
    case "not_ready":
      return "This room isn’t finished arriving yet. Once it’s standing, I can draw you a card of it.";
    case "undated":
      return "I can’t tell when this room was scanned, and I’d rather not guess about that one. A fresh scan would settle it.";
  }
}

const NO_CONTOUR =
  "There’s no measured floor for this room — the scan didn’t give me an outline I could draw. A slower pass around the walls would.";

/** Painted at 2× so the downloaded file is a usable share image; the
 * preview is the same canvas at CSS width. */
const EXPORT_SCALE = 2;

function CardCanvas({
  layout,
  onReady,
}: {
  layout: CardLayout;
  onReady: (canvas: HTMLCanvasElement) => void;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const [painted, setPainted] = useState(false);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    let cancelled = false;
    setPainted(false);
    (async () => {
      const fonts = resolveFonts(document);
      // next/font loads by face on demand, and canvas text does not
      // trigger a load — it silently falls back. So wait, then paint once.
      await ensureCardFonts(document, layout, fonts);
      if (cancelled) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(EXPORT_SCALE, 0, 0, EXPORT_SCALE, 0, 0);
      paintCard(ctx, layout, fonts);
      setPainted(true);
      onReady(canvas);
    })();
    return () => {
      cancelled = true;
    };
  }, [layout, onReady]);

  return (
    <div
      className="relative w-full overflow-hidden rounded-[14px] ring-1 ring-inset ring-ink/[0.06]"
      style={{ aspectRatio: `${layout.width} / ${layout.height}` }}
    >
      {!painted && <div className="hatch breathe absolute inset-0" aria-hidden />}
      <canvas
        ref={ref}
        width={layout.width * EXPORT_SCALE}
        height={layout.height * EXPORT_SCALE}
        className="block h-full w-full"
        style={{ opacity: painted ? 1 : 0, transition: "opacity 240ms ease" }}
        role="img"
        aria-label={`A measured floor plan of ${layout.claims.title}`}
      />
    </div>
  );
}

export default function CallingCardSheet({
  open,
  onClose,
  status,
  createdAt,
  shell,
  manifest,
}: {
  open: boolean;
  onClose: () => void;
  status: string;
  createdAt: string;
  shell: ShellDoc | null | undefined;
  manifest: SceneManifest | null | undefined;
}) {
  const [variant, setVariant] = useState<CardVariant>("landscape");
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const onReady = useCallback((canvas: HTMLCanvasElement) => {
    canvasRef.current = canvas;
  }, []);

  const gate = cardEligibility({ status, created_at: createdAt });
  const title = roomTitle(createdAt);
  const measure = gate.eligible ? measureRoom(shell, manifest) : null;
  const layout: CardLayout | null = measure
    ? layoutCard({ measure, title, variant })
    : null;

  const download = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = cardFileName(title);
      a.click();
      // Revoked on the next frame: the click has already been dispatched
      // and the browser has taken its own reference to the blob.
      requestAnimationFrame(() => URL.revokeObjectURL(url));
    }, "image/png");
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      label={COPY.heading}
      className={layout ? "max-w-[860px] p-6 sm:p-8" : "max-w-[520px] p-8"}
    >
      {layout ? (
        <div className="grid items-center gap-8 md:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <CardCanvas layout={layout} onReady={onReady} />
          <div>
            <SheetTitle>{COPY.heading}</SheetTitle>
            <p className="mt-3.5 text-[15.5px] leading-[1.55] text-ink-2">{COPY.discloses}</p>
            <div className="mt-5 flex items-center gap-1.5" role="group" aria-label="Card shape">
              {(
                [
                  ["landscape", COPY.frameLandscape],
                  ["square", COPY.frameSquare],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setVariant(key)}
                  aria-pressed={variant === key}
                  className={`h-9 cursor-pointer rounded-full px-4 text-[14px] font-medium transition-colors ${
                    variant === key
                      ? "bg-parchment text-ink"
                      : "text-ink-2 hover:bg-paper hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <PillButton onClick={download} className="h-12 px-6 text-[15px]">
                {COPY.download}
              </PillButton>
              <PillButton variant="ghost" onClick={onClose} className="h-12 px-6 text-[15px]">
                Close
              </PillButton>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-start justify-between gap-4">
            <SheetTitle>{COPY.heading}</SheetTitle>
            <CloseButton onClick={onClose} />
          </div>
          <GuestLine className="mt-4 text-[18px] leading-[1.5]">
            {gate.eligible ? NO_CONTOUR : refusalLine(gate.reason)}
          </GuestLine>
        </>
      )}
    </Dialog>
  );
}

/** The quiet control that opens it. */
export function CallingCardButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="pointer-events-auto inline-flex h-[42px] cursor-pointer items-center gap-2 whitespace-nowrap rounded-full px-4 text-sm font-medium text-on-dusk ring-1 ring-inset ring-on-dusk/20 transition-colors hover:bg-dusk-3"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M7 15h5" />
      </svg>
      {COPY.open}
    </button>
  );
}
