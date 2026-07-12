"""Quality-gate scoring logic (no GPU, no models — pure functions)."""
from scripts.tts_quality_gate import GateThresholds, Verdict, score_experiment


def test_pass_when_all_deltas_within_thresholds() -> None:
    v = score_experiment(
        baseline={"cer": 0.05, "sim": 0.80},
        candidate={"cer": 0.052, "sim": 0.79},
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.PASS


def test_fail_on_cer_regression() -> None:
    v = score_experiment(
        baseline={"cer": 0.05, "sim": 0.80},
        candidate={"cer": 0.061, "sim": 0.80},  # +1.1 п.п. > 0.5
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.FAIL
    assert "cer" in v.reasons[0].lower()


def test_warn_zone_requests_blind_ab() -> None:
    v = score_experiment(
        baseline={"cer": 0.05, "sim": 0.80},
        candidate={"cer": 0.054, "sim": 0.785},  # sim −0.015: в warn-зоне ≤0.02
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.WARN


def test_sim_none_degrades_to_warn_not_crash() -> None:
    # ECAPA (speechbrain) может быть не установлен — гейт честно WARN, не падает.
    v = score_experiment(
        baseline={"cer": 0.05, "sim": None},
        candidate={"cer": 0.05, "sim": None},
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.WARN
