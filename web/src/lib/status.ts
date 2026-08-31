/**
 * SceneStatus display semantics, mirroring the iOS ScenePollState
 * classification (ios/TheGoodGuestCapture/TheGoodGuestCapture/Scene/ScenePoller.swift):
 * in-flight states keep
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
    description: "Your scan made the trip. The rebuild starts in a moment.",
  },
  processing: {
    label: "Being rebuilt",
    tone: "progress",
    terminal: false,
    description:
      "The room is being rebuilt — each piece found, remade in 3D, and placed where it stands.",
  },
  ready: {
    label: "Ready",
    tone: "success",
    terminal: true,
    description: "Rebuilt and waiting. Step inside.",
  },
  failed: {
    label: "Didn't survive",
    tone: "error",
    terminal: true,
    description:
      "The scan didn't survive the trip. One more slow pass usually fixes it.",
  },
  failed_incomplete: {
    label: "Partly arrived",
    tone: "warning",
    terminal: false,
    description:
      "Part of the scan never arrived. Reopen the iOS app and it picks up where it left off.",
  },
  failed_invalid: {
    label: "Unreadable scan",
    tone: "error",
    terminal: true,
    description:
      "This scan arrived in a form that can't be read. One more slow pass and we'll get it.",
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
