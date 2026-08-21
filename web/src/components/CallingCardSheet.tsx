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

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { PillButton, SPRING } from "@/components/ui/spring";
import { Eyebrow, GuestLine } from "@/components/ui/voice";
import type { SceneManifest, ShellDoc } from "@/lib/api/types";
import { cardEligibility, type CardRefusal } from "@/lib/card/eligibility";
import {
  CARD_FRAMES,
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
  open: "make a card",
  heading: "A card for this room",
  /** §9's obligation: the flow says what is about to be visible. At rung 0
   * the honest answer is short, and it includes what a floor plan with true
   * dimensions does disclose (§3.2). */
  discloses:
    "It carries the room's shape and three of its measurements. No photographs, none of your things, and nothing that points back to your account — a floor plan and its dimensions, and that is all.",
  download: "Download",
  frameLandscape: "wide",
  frameSquare: "square",
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
      className="relative w-full overflow-hidden rounded-xl border border-ink/10 shadow-lift"
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

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-6 backdrop-blur-sm"
          onClick={onClose}
          role="dialog"
          aria-modal="true"
          aria-label={COPY.heading}
        >
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={SPRING}
            className="relative w-full max-w-3xl rounded-3xl border border-ink/15 bg-paper p-8 shadow-deep sm:p-10"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="absolute right-5 top-5 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full text-ink/50 transition-colors hover:bg-ink/[0.06] hover:text-ink"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                <path
                  d="M2 2l10 10M12 2L2 12"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>

            {layout ? (
              <>
                <Eyebrow>{COPY.heading}</Eyebrow>
                <div className="mt-4">
                  <CardCanvas layout={layout} onReady={onReady} />
                </div>
                <p className="mt-5 max-w-xl text-[12.5px] leading-relaxed text-ink/60">
                  {COPY.discloses}
                </p>
                <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
                  <div
                    className="flex items-center gap-1.5"
                    role="group"
                    aria-label="Card shape"
                  >
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
                        className={`cursor-pointer rounded-full border px-3.5 py-1.5 text-[11.5px] transition-colors ${
                          variant === key
                            ? "border-ink/45 text-ink"
                            : "border-ink/15 text-ink/50 hover:border-ink/30 hover:text-ink/75"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                    <span className="ml-2 font-mono text-[10.5px] text-ink/35">
                      {CARD_FRAMES[variant].w * EXPORT_SCALE}×
                      {CARD_FRAMES[variant].h * EXPORT_SCALE}
                    </span>
                  </div>
                  <PillButton onClick={download}>{COPY.download}</PillButton>
                </div>
              </>
            ) : (
              <div className="max-w-lg py-4">
                <GuestLine className="text-[16px]">
                  {gate.eligible ? NO_CONTOUR : refusalLine(gate.reason)}
                </GuestLine>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/** The quiet control that opens it. */
export function CallingCardButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="pointer-events-auto cursor-pointer whitespace-nowrap rounded-full border border-ink/15 bg-paper/90 px-3.5 py-1.5 text-xs text-ink/70 transition-colors hover:border-ink/35 hover:text-ink"
    >
      {COPY.open}
    </button>
  );
}
