"use client";

/**
 * "New room" as a sheet, not a destination. Scanning happens in the iOS
 * app, so the web's only job here is a moment of instruction — and a
 * moment shouldn't cost the user their place in the app. The sheet opens
 * over whatever they were doing (nav CTA, rooms empty state, landing) and
 * closes back to it. /new remains as a deep-linkable standalone page
 * rendering the same ScanInstructions.
 *
 * One sheet instance lives in SiteNav; anything can open it by calling
 * openNewRoomSheet(), which dispatches a DOM event the instance listens
 * for. A custom event instead of React context keeps the server layout
 * free of a client provider wrapping the whole tree.
 */

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { SPRING } from "@/components/ui/spring";

const OPEN_EVENT = "roomstudio:open-new-room";

export function openNewRoomSheet() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

/** The scan instructions themselves — shared by the sheet and /new. */
export function ScanInstructions() {
  return (
    <div className="flex flex-col items-center text-center">
      <h2 className="max-w-xl text-balance text-3xl font-semibold leading-tight tracking-[-0.02em] sm:text-4xl">
        It starts with a slow walk around the room.
      </h2>
      <p className="mt-5 max-w-md text-pretty text-sm leading-relaxed text-zinc-400">
        Open the iOS app and scan the space — about a minute. Your iPhone
        measures what a photo can only guess at: true distances, depth, and
        where every object actually stands.
      </p>

      <div className="mt-12 grid w-full gap-8 text-left sm:grid-cols-3">
        {[
          { n: "01", text: "Open the iOS app on your iPhone" },
          { n: "02", text: "Walk the room slowly, corners included" },
          { n: "03", text: "That's it — analysis starts on its own" },
        ].map((step) => (
          <div key={step.n}>
            <p className="text-xs font-medium text-zinc-600">{step.n}</p>
            <p className="mt-2 text-sm leading-relaxed text-zinc-300">{step.text}</p>
          </div>
        ))}
      </div>

      <p className="mt-12 text-xs text-zinc-600">
        The room appears here on its own when the scan lands. LiDAR-equipped
        iPhones give the most faithful rooms.
      </p>
    </div>
  );
}

export default function NewRoomSheet() {
  const [open, setOpen] = useState(false);
  // Portal target exists only after mount (SSG renders no document).
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!mounted) return null;

  // Portaled to <body>: the nav header's backdrop-filter would otherwise
  // become this fixed overlay's containing block, pinning the "fixed"
  // sheet to the header instead of the viewport.
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm"
          onClick={() => setOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Scan a new room"
        >
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={SPRING}
            className="relative w-full max-w-2xl rounded-3xl border border-white/[0.08] bg-[#101010] p-10 shadow-2xl shadow-black/60 sm:p-14"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close"
              className="absolute right-5 top-5 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full text-zinc-500 transition-colors hover:bg-white/[0.06] hover:text-zinc-200"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
            <ScanInstructions />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
