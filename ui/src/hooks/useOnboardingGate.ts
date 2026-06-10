import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useOnboardingStore } from "../stores/onboardingStore";

export interface OnboardingGateResult {
  loading: boolean;
  gated: boolean;
}

export function useOnboardingGate(): OnboardingGateResult {
  const [loading, setLoading] = useState(true);
  const [gated, setGated] = useState(true);
  const storeCompleted = useOnboardingStore((s) => s.completed);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const RETRY_MS = 1500;
    const DEADLINE_MS = 30000;
    const deadline = Date.now() + DEADLINE_MS;

    // The backend may still be booting on a fresh launch. A failed fetch must
    // NOT be treated as "not onboarded" (that would re-show the wizard to
    // returning users), so we keep `loading` and retry with backoff until we
    // get a definitive response or hit the deadline.
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
          if (Date.now() >= deadline) {
            // Backend never answered — fall back to the wizard.
            setGated(true);
            setLoading(false);
            return;
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
    loading,
    gated: gated && !storeCompleted,
  };
}
