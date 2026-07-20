"use client";

/**
 * Deep-linkable standalone form of the scan instructions (e.g. a future QR
 * code or shared link). In-app, "New room" opens NewRoomSheet in place —
 * this page is not in the nav.
 */

import { ScanInstructions } from "@/components/NewRoomSheet";

export default function NewRoomPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-24">
      <ScanInstructions />
    </div>
  );
}
