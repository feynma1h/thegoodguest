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
    label: "Queued",
    tone: "progress",
    terminal: false,
    description: "Waiting for a reconstruction worker.",
  },
  processing: {
    label: "Processing",
    tone: "progress",
    terminal: false,
    description: "Reconstructing your room — this can take a few minutes.",
  },
  ready: {
    label: "Ready",
    tone: "success",
    terminal: true,
    description: "Your room is ready to explore.",
  },
  failed: {
    label: "Failed",
    tone: "error",
    terminal: true,
    description: "Reconstruction failed. Try capturing the room again.",
  },
  failed_incomplete: {
    label: "Upload incomplete",
    tone: "warning",
    terminal: false,
    description: "Some capture files never arrived. Reopen the iOS app to finish uploading.",
  },
  failed_invalid: {
    label: "Invalid capture",
    tone: "error",
    terminal: true,
    description: "The capture couldn't be read. Try capturing the room again.",
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
