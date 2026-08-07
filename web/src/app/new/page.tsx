"use client";

/**
 * The Bridge (design §2): capture is iOS-only; this desk is where the
 * room arrives. The page frames the handoff — and the desk genuinely
 * waits: it polls the scene list, and when a scan it hasn't seen before
 * lands, the listening panel swells, the guest takes the room in, and
 * the page walks into the wait in place (no filename ever shows).
 *
 * The QR block is a DECLARED placeholder — no deep link exists yet, and
 * the caption says so. Nothing on this page pretends to work.
 */

import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import SignInPanel from "@/components/SignInPanel";
import { SPRING } from "@/components/ui/spring";
import { Eyebrow, GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";

const POLL_MS = 10_000;
const HEARD_LINGER_MS = 1_600;

type Listening =
  | { phase: "listening"; trouble: boolean }
  | { phase: "signed-out" }
  | { phase: "heard"; bundleId: string | null };

export default function BridgePage() {
  const router = useRouter();
  const [state, setState] = useState<Listening>({
    phase: "listening",
    trouble: false,
  });

  // The desk listens: baseline the visible scenes, then watch for one it
  // hasn't seen. All setState happens in async continuations.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const known = new Set<string>();
    let baselined = false;

    const tick = () => {
      getApiClient()
        .listScenes()
        .then((scenes) => {
          if (cancelled) return;
          if (!baselined) {
            for (const s of scenes) known.add(s.scene_id);
            baselined = true;
            setState({ phase: "listening", trouble: false });
          } else {
            const fresh = scenes.find((s) => !known.has(s.scene_id));
            if (fresh) {
              setState({ phase: "heard", bundleId: fresh.bundle_id });
              return; // the wait takes over from here
            }
            setState({ phase: "listening", trouble: false });
          }
          timer = window.setTimeout(tick, POLL_MS);
        })
        .catch((exc: unknown) => {
          if (cancelled) return;
          // no_local_token = live mode, nobody signed in (decision 0051).
          // The desk can't listen for an account that isn't here; stop
          // polling — sign-in reloads the page and starts fresh.
          if (exc instanceof ApiError && exc.code === "no_local_token") {
            setState((s) => (s.phase === "heard" ? s : { phase: "signed-out" }));
            return;
          }
          setState((s) =>
            s.phase === "heard" ? s : { phase: "listening", trouble: true },
          );
          timer = window.setTimeout(tick, POLL_MS);
        });
    };
    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, []);

  // A heard room lingers for a breath, then the wait begins in place.
  useEffect(() => {
    if (state.phase !== "heard") return;
    const target =
      state.bundleId !== null ? `/room?bundle=${state.bundleId}` : "/rooms";
    const timer = window.setTimeout(() => router.push(target), HEARD_LINGER_MS);
    return () => clearTimeout(timer);
  }, [state, router]);

  const heard = state.phase === "heard";

  return (
    <div className="mx-auto max-w-5xl px-6 py-16">
      <Eyebrow>The bridge — phone to desk</Eyebrow>

      <div className="mt-10 grid gap-12 lg:grid-cols-[auto_1fr] lg:gap-16">
        <div className="w-[180px]">
          <div className="flex h-[180px] w-[180px] items-center justify-center rounded-[14px] border-2 border-ink bg-white">
            <div
              aria-hidden
              className="h-[124px] w-[124px] rounded-[4px] opacity-85"
              style={{
                background:
                  "repeating-conic-gradient(var(--ink) 0% 25%, #fff 0% 50%) 0 0 / 24px 24px",
              }}
            />
          </div>
          <p className="mt-3 max-w-[180px] text-center text-[11.5px] leading-relaxed text-ink/55">
            one day you&rsquo;ll point your phone here — the shortcut
            isn&rsquo;t wired yet
          </p>
        </div>

        <div className="max-w-xl">
          <h1 className="font-serif text-[clamp(1.5rem,2.4vw,1.7rem)] font-normal leading-[1.4]">
            Your phone does the walking. This desk is where the room arrives.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-ink/70">
            Open the iOS app and walk the room slowly — a minute or two,
            corners included. The moment you finish, the scan travels here on
            its own; leave this window open and watch it land.
          </p>

          <motion.div
            animate={{ scale: heard ? 1.03 : 1 }}
            transition={SPRING}
            className="mt-9 rounded-xl border-[1.5px] border-dashed border-ink/35 bg-white/50 px-5 py-4"
          >
            {state.phase === "heard" ? (
              <GuestLine className="text-[15px]">
                It&rsquo;s here. Give me a few minutes with it.
              </GuestLine>
            ) : state.phase === "signed-out" ? (
              <>
                <p className="text-[13.5px] font-medium">
                  The desk listens for the rooms of an account — sign in with
                  the one from your iPhone.
                </p>
                <div className="mt-3">
                  <SignInPanel compact />
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2.5">
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${
                      state.trouble
                        ? "bg-ink/30"
                        : "animate-pulse bg-sun shadow-[0_0_0_5px_rgba(201,162,94,0.2)]"
                    }`}
                  />
                  <span className="text-[13.5px] font-medium">
                    {state.trouble
                      ? "The desk can’t hear the server right now — still trying."
                      : "This desk is listening for your scan…"}
                  </span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-ink/55">
                  finish a scan on your iPhone and the room lands here on its
                  own — no upload buttons, no files
                </p>
              </>
            )}
          </motion.div>

          <p className="mt-8 text-xs text-ink/45">
            LiDAR-equipped iPhones give the most faithful rooms.
          </p>
        </div>
      </div>
    </div>
  );
}
