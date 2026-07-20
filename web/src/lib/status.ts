/**
 * SceneStatus display semantics, mirroring the iOS ScenePollState
 * classification (ios/.../Scene/ScenePoller.swift): in-flight states keep
 * polling, failed_incomplete is recoverable (re-upload of missing files),
 * ready/failed/failed_invalid are terminal.
 */

import type { SceneStatus } from "./api/types";

export type StatusTone = "progress" | "success" | "warning" | "error";

export interface StatusMeta {
  label: string;
  tone: StatusTone;
  terminal: boolean;
  description: string;
}

const META: Record<SceneStatus, StatusMeta> = {
  queued: {
    label: "In line",
    tone: "progress",
    terminal: false,
    description: "Your scan arrived. Analysis begins in a moment.",
  },
  processing: {
    label: "Analyzing",
    tone: "progress",
    terminal: false,
    description:
      "Reading the room — finding every object, rebuilding it in 3D, and placing it exactly where it stands.",
  },
  ready: {
    label: "Ready",
    tone: "success",
    terminal: true,
    description: "Analyzed and rebuilt. Step inside.",
  },
  failed: {
    label: "Failed",
    tone: "error",
    terminal: true,
    description: "The analysis didn't finish. A fresh scan usually fixes this.",
  },
  failed_incomplete: {
    label: "Upload incomplete",
    tone: "warning",
    terminal: false,
    description:
      "Some of the scan never arrived. Reopen the iOS app to finish uploading.",
  },
  failed_invalid: {
    label: "Unreadable scan",
    tone: "error",
    terminal: true,
    description: "This scan couldn't be read. Try scanning the room again.",
  },
};

export function statusMeta(status: SceneStatus): StatusMeta {
  return META[status] ?? {
    label: status,
    tone: "warning",
    terminal: false,
    description: "Unknown status.",
  };
}
