"use client";

/**
 * The one frame every sheet sits in (decision 0361): a white panel on a
 * soft ink scrim, rising on the single SPRING. The scan sheet, the calling
 * card and the account deletion all use it, so they open, close and trap
 * attention the same way.
 *
 * Escape and a click on the scrim close it; focus moves into the panel when
 * it opens and goes back to whatever held it when it closes. Portaled to
 * <body>, because the nav header's backdrop-filter would otherwise become a
 * fixed overlay's containing block and pin it to the header.
 */

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { SPRING } from "@/components/ui/spring";

const emptySubscribe = () => () => {};

export function Dialog({
  open,
  onClose,
  label,
  alert = false,
  className,
  children,
}: {
  open: boolean;
  onClose: () => void;
  /** The dialog's accessible name. */
  label: string;
  /** An irreversible choice: announced as an alert dialog. */
  alert?: boolean;
  /** Width and padding of the panel. */
  className?: string;
  children: React.ReactNode;
}) {
  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
  const panelRef = useRef<HTMLDivElement | null>(null);
  // Read at call time so a new onClose identity never re-arms the listeners.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const returnTo = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    // After the panel mounts: focus its first control, else the panel. An
    // alert dialog takes focus on the panel itself, so the irreversible
    // button is never one stray Enter away.
    const t = window.setTimeout(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const first = panel.querySelector<HTMLElement>(
        "button:not([disabled]), a[href], input:not([disabled])",
      );
      (alert ? panel : (first ?? panel)).focus();
    }, 0);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
      returnTo?.focus?.();
    };
  }, [open, alert]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm sm:p-6"
          onClick={onClose}
        >
          <motion.div
            ref={panelRef}
            role={alert ? "alertdialog" : "dialog"}
            aria-modal="true"
            aria-label={label}
            tabIndex={-1}
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={SPRING}
            className={`relative max-h-[calc(100dvh-2rem)] w-full overflow-y-auto rounded-3xl bg-white shadow-deep outline-none ${className ?? ""}`}
            onClick={(e) => e.stopPropagation()}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/** The round close control every sheet carries in its corner. */
export function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Close"
      className="grid h-9 w-9 shrink-0 cursor-pointer place-items-center rounded-full bg-paper text-ink transition-colors hover:bg-parchment"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
        <path d="M2 2l10 10M12 2L2 12" />
      </svg>
    </button>
  );
}

/** A sheet's heading: the display face, light, set close. */
export function SheetTitle({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="font-serif text-[34px] font-light leading-[1.05] tracking-[-0.02em] text-ink">
      {children}
    </h2>
  );
}
