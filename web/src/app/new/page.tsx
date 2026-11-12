"use client";

/**
 * The Bridge (design §2, decision 0361): capture is iOS-only; this desk is
 * where the room arrives. The page says how the handoff goes, and the desk
 * genuinely waits: it polls the scene list, and when a scan it hasn't seen
 * before lands, the listening panel says so and the page walks into the
 * wait in place (no filename ever shows).
 *
 * Nothing here pretends to work: the old QR placeholder is gone, and the
 * panel names the account it is listening for, because that is the one
 * thing that decides whether a scan will land here.
 */

import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import SignInPanel from "@/components/SignInPanel";
import { signedInWith, useAccount } from "@/components/useAccount";
import { SPRING } from "@/components/ui/spring";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";

const POLL_MS = 10_000;
const HEARD_LINGER_MS = 1_600;

type Listening =
  | { phase: "listening"; trouble: boolean }
  | { phase: "signed-out" }
  | { phase: "heard"; bundleId: string | null };

const STEPS = [
  {
    text: "Open The Good Guest on your iPhone and tap Scan a room.",
    icon: (
      <>
        <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
        <path d="M11 18.5h2" />
      </>
    ),
  },
  {
    text: "Walk the room slowly, corners included. A minute or two is enough.",
    icon: (
      <>
        <path d="M4 20V9l8-5 8 5v11" />
        <path d="M9 20v-6h6v6" />
      </>
    ),
  },
  {
    text: "Leave this page open. The room lands here on its own.",
    icon: (
      <>
        <rect x="3" y="4.5" width="18" height="12" rx="1.5" />
        <path d="M8 20h8M12 16.5V20" />
      </>
    ),
  },
] as const;

export default function BridgePage() {
  const router = useRouter();
  const account = useAccount();
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

  const live = state.phase === "listening" && !state.trouble;
  const status =
    state.phase === "heard"
      ? "It’s here"
      : state.phase === "signed-out"
        ? "Not listening yet"
        : state.trouble
          ? "Can’t reach the server — still trying"
          : "Listening for your scan";
  const line =
    state.phase === "heard"
      ? "It’s here. Give me a few minutes with it."
      : state.phase === "signed-out"
        ? "Sign in with the account from your iPhone, and I’ll listen for its rooms."
        : "I’ll know the moment it arrives, and I’ll start getting to know the room.";
  const foot =
    state.phase === "heard"
      ? "Opening the room…"
      : account.phase === "demo"
        ? "Demo workspace. Sample rooms stand in for yours."
        : account.phase === "signedIn"
          ? `${signedInWith(account)}. Rooms you scan on that account appear here.`
          : null;

  return (
    <div className="mx-auto grid max-w-[1280px] items-center gap-12 px-6 pb-20 pt-12 sm:px-10 lg:grid-cols-2 lg:gap-[72px] lg:pt-16">
      <div>
        <h1 className="font-serif text-[clamp(40px,4.6vw,64px)] font-light leading-[1.02] tracking-[-0.03em] text-ink">
          Your phone does the walking. This desk is where the room arrives.
        </h1>
        <ol className="mt-11 flex flex-col gap-[22px]">
          {STEPS.map((step) => (
            <li key={step.text} className="flex items-start gap-4">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="mt-0.5 shrink-0 text-ink">
                {step.icon}
              </svg>
              <span className="text-[18px] leading-normal text-ink">{step.text}</span>
            </li>
          ))}
        </ol>
        <p className="mt-9 text-[15px] leading-normal text-ink-2">
          Works on any iPhone. Pro models give the best scans.
        </p>
      </div>

      <motion.section
        aria-label={status}
        aria-live="polite"
        animate={{ scale: state.phase === "heard" ? 1.02 : 1 }}
        transition={SPRING}
        className="flex min-h-[460px] flex-col justify-between gap-10 rounded-[28px] bg-dusk p-8 text-on-dusk sm:p-10"
      >
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className={`h-3 w-3 rounded-full ${
              live
                ? "breathe bg-sun shadow-[0_0_22px_rgba(240,178,106,0.7)]"
                : state.phase === "heard"
                  ? "bg-sun"
                  : "bg-on-dusk/30"
            }`}
          />
          <span className="text-[15px] font-semibold">{status}</span>
        </div>
        <p className="max-w-[22ch] font-serif text-[clamp(24px,2.3vw,30px)] italic leading-[1.3] tracking-[-0.01em]">
          {line}
        </p>
        {state.phase === "signed-out" ? (
          <div className="max-w-sm">
            <SignInPanel compact tone="dark" />
          </div>
        ) : (
          foot && <p className="text-[14px] text-on-dusk-2">{foot}</p>
        )}
      </motion.section>
    </div>
  );
}
