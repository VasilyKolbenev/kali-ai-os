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
    api
      .settings()
      .then((s) => {
        if (cancelled) return;
        const done = s["onboarding_completed"] === true;
        setGated(!done);
        if (done) {
          useOnboardingStore.setState({ completed: true });
        }
      })
      .catch(() => {
        if (!cancelled) setGated(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    loading,
    gated: gated && !storeCompleted,
  };
}
