import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useOnboardingStore } from "../stores/onboardingStore";

export interface OnboardingGateResult {
  loading: boolean;
  gated: boolean;
  /** Kernel is taking unusually long to answer — let the splash explain. */
  slow: boolean;
}

export function useOnboardingGate(): OnboardingGateResult {
  const [loading, setLoading] = useState(true);
  const [gated, setGated] = useState(true);
  const [slow, setSlow] = useState(false);
  const storeCompleted = useOnboardingStore((s) => s.completed);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const RETRY_MS = 1500;
    const SLOW_AFTER_MS = 20000;
    const start = Date.now();

    // A failed fetch must NOT fall back to the wizard: a cold backend boots
    // models for 40-60 s, and re-gating a returning user re-asks for their
    // API key against a dead kernel («Failed to fetch» on every button).
    // The wizard is shown only on a definitive "not onboarded" answer from a
    // LIVE backend; until then we keep polling and the splash explains the
    // wait. A locally persisted `completed` flag skips the splash entirely
    // for returning users (the kernel-offline banner covers a dead backend).
    const poll = () => {
      api
        .settings()
        .then((s) => {
          if (cancelled) return;
          const done = s["onboarding_completed"] === true;
          setGated(!done);
          if (done) {
            useOnboardingStore.setState({ completed: true });
          }
          setLoading(false);
        })
        .catch(() => {
          if (cancelled) return;
          if (Date.now() - start >= SLOW_AFTER_MS) {
            setSlow(true);
          }
          timer = setTimeout(poll, RETRY_MS);
        });
    };

    poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return {
    loading: loading && !storeCompleted,
    gated: gated && !storeCompleted,
    slow,
  };
}
