"use client";

/**
 * The House: GET /scenes as sibling rooms (design §9 — no floor plan,
 * no map; each room its own conversation). Client-side fetch — the
 * static export has no server; data loads after hydration through the
 * ApiClient (mock fixtures or live api-public depending on mode).
 */

import { motion } from "motion/react";
import { useEffect, useState } from "react";

import RoomCard from "@/components/RoomCard";
import { openNewRoomSheet } from "@/components/NewRoomSheet";
import { PillLink } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";
import { smallCount } from "@/lib/voice";

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; scenes: SceneSummary[] };

export default function RoomsPage() {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .listScenes()
      .then((scenes) => !cancelled && setState({ phase: "ready", scenes }))
      .catch((exc: unknown) => {
        if (cancelled) return;
        const message =
          exc instanceof ApiError ? exc.message : "Could not reach the server.";
        setState({ phase: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const count = state.phase === "ready" ? state.scenes.length : null;

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h1 className="font-serif text-[26px] italic tracking-[-0.01em]">
          your house
          {count !== null && count > 0 && (
            <span className="text-ink/60">
              {" "}
              — {smallCount(count)} {count === 1 ? "room" : "rooms"} so far
            </span>
          )}
        </h1>
        <p className="hidden text-xs text-ink/45 lg:block">
          no floor plan, no map — rooms are siblings, each its own conversation
        </p>
      </div>

      {state.phase === "loading" && (
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-72 animate-pulse rounded-xl border border-ink/10 bg-parchment/60"
            />
          ))}
        </div>
      )}

      {state.phase === "error" && (
        <div className="mt-10 rounded-xl border border-accent/25 bg-accent/5 p-6">
          <p className="text-sm font-medium text-accent">
            Couldn&apos;t reach your house
          </p>
          <p className="mt-1 text-sm text-ink/60">{state.message}</p>
        </div>
      )}

      {state.phase === "ready" && state.scenes.length === 0 && (
        <div className="mt-28 flex flex-col items-center text-center">
          <GuestLine className="max-w-md text-[19px]">
            One room is a conversation. A house is a life — whenever
            you&rsquo;re ready.
          </GuestLine>
          <PillLink href="/new" className="mt-9">
            Scan your first room
          </PillLink>
        </div>
      )}

      {state.phase === "ready" && state.scenes.length > 0 && (
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {state.scenes.map((scene, i) => (
            <motion.div
              key={scene.scene_id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1], delay: i * 0.06 }}
            >
              <RoomCard scene={scene} />
            </motion.div>
          ))}
          <motion.button
            type="button"
            onClick={openNewRoomSheet}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.5,
              ease: [0.22, 1, 0.36, 1],
              delay: state.scenes.length * 0.06,
            }}
            className="flex h-72 cursor-pointer flex-col items-center justify-center gap-2.5 rounded-xl border-[1.5px] border-dashed border-ink/35 text-ink/70 transition-colors hover:border-ink/60 hover:text-ink"
          >
            <span aria-hidden className="text-2xl font-light text-ink/40">
              +
            </span>
            <span className="text-[13px] font-medium">scan another room</span>
          </motion.button>
        </div>
      )}
    </div>
  );
}
