import time

from app import rate_ledger


def test_near_ceiling_false_with_no_history():
    assert rate_ledger.near_ceiling("p1", "p1/model-a") is False


def test_near_ceiling_true_once_the_learned_ceiling_is_reached():
    rate_ledger.record_attempt("p1", "p1/model-a")
    rate_ledger.record_rate_limit_hit("p1", "p1/model-a")  # 1 request seen -> ceiling = 1

    assert rate_ledger.near_ceiling("p1", "p1/model-a") is True


def test_ceiling_only_ever_tightens_never_loosens():
    for _ in range(5):
        rate_ledger.record_attempt("p1", "p1/model-a")
    rate_ledger.record_rate_limit_hit("p1", "p1/model-a")  # 5 requests seen -> ceiling = 5

    # A 6th request comes in, then a looser 429 (6 seen) — the ceiling must
    # stay at the tighter value of 5, not relax to 6.
    rate_ledger.record_attempt("p1", "p1/model-a")
    rate_ledger.record_rate_limit_hit("p1", "p1/model-a")

    # 5 requests are already in-window from the setup above, so a model with a
    # ceiling of 6 would still read as "not near" — assert it reads as near,
    # proving the ceiling held at 5 rather than relaxing to 6.
    assert rate_ledger.near_ceiling("p1", "p1/model-a") is True


def test_window_pruning_forgets_old_requests(monkeypatch):
    monkeypatch.setenv("RATE_LEDGER_WINDOW_SECONDS", "0.05")
    rate_ledger.record_attempt("p1", "p1/model-a")
    rate_ledger.record_rate_limit_hit("p1", "p1/model-a")  # ceiling = 1
    assert rate_ledger.near_ceiling("p1", "p1/model-a") is True

    time.sleep(0.06)
    # The one request that triggered the ceiling is now outside the window.
    assert rate_ledger.near_ceiling("p1", "p1/model-a") is False


def test_learned_ceiling_expires_after_its_ttl(monkeypatch):
    monkeypatch.setenv("RATE_LEDGER_CEILING_TTL_SECONDS", "0.05")
    rate_ledger.record_attempt("p1", "p1/model-a")
    rate_ledger.record_rate_limit_hit("p1", "p1/model-a")
    assert rate_ledger.near_ceiling("p1", "p1/model-a") is True

    time.sleep(0.06)
    assert rate_ledger.near_ceiling("p1", "p1/model-a") is False


def test_different_models_are_tracked_independently():
    rate_ledger.record_attempt("p1", "p1/model-a")
    rate_ledger.record_rate_limit_hit("p1", "p1/model-a")

    assert rate_ledger.near_ceiling("p1", "p1/model-a") is True
    assert rate_ledger.near_ceiling("p1", "p1/model-b") is False
    assert rate_ledger.near_ceiling("p2", "p1/model-a") is False
