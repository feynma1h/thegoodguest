"use client";

/**
 * "Scan a room" as a sheet, not a destination. Scanning happens in the iOS
 * app, so the web's only job here is a moment of instruction — and a moment
 * shouldn't cost the user their place in the site. The sheet opens over
 * whatever they were doing and closes back to it. /new remains as the
 * deep-linkable page that also listens for the scan to land.
 *
 * One sheet instance lives in SiteNav; anything can open it by calling
 * openNewRoomSheet(), which dispatches a DOM event the instance listens for.
 * A custom event instead of React context keeps the server layout free of a
 * client provider wrapping the whole tree.
 */

import { useEffect, useState } from "react";

import { CloseButton, Dialog, SheetTitle } from "@/components/ui/Dialog";
import { PillButton } from "@/components/ui/spring";

const OPEN_EVENT = "thegoodguest:open-new-room";

export function openNewRoomSheet() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

const STEPS = [
  "Open The Good Guest on your iPhone.",
  "Walk the room slowly, corners included.",
  "That’s it. The room travels here on its own.",
] as const;

export default function NewRoomSheet() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  const close = () => setOpen(false);

  return (
    <Dialog open={open} onClose={close} label="Scan a new room" className="max-w-[460px] p-8">
      <div className="flex items-start justify-between gap-4">
        <SheetTitle>Scan a new room</SheetTitle>
        <CloseButton onClick={close} />
      </div>
      <ol className="mt-6 flex flex-col gap-4">
        {STEPS.map((step, i) => (
          <li key={step} className="flex gap-3.5 text-[16.5px] leading-normal text-ink">
            <span aria-hidden className="w-3.5 font-serif text-[20px] leading-[1.25] text-ink-3">
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>
      <p className="mb-6 mt-5 text-[14px] text-ink-2">
        Works on any iPhone. Pro models give the best scans.
      </p>
      <PillButton onClick={close} className="h-12 px-6 text-[15px]">
        Got it
      </PillButton>
    </Dialog>
  );
}
