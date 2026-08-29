"""Tests are hermetic: no live DB or providers.

The docker-compose service loads the real DATABASE_URL from .env; if the tests
inherit it they hit the production database (registered agents flip /v1 and
/admin into protected mode, and the DB registry replaces the YAML fixtures).
Dropping the variable before app modules import makes every storage call fail
fast, exercising the same fallbacks a DB outage does.
"""

import os

import pytest

os.environ.pop("DATABASE_URL", None)


@pytest.fixture(autouse=True)
def _reset_routing_state():
    # Circuit breaker, sticky routing and the performance cache are process-global;
    # leaking them across tests would change candidate ordering unpredictably.
    from app.routing_state import reset

    reset()
    yield


@pytest.fixture(autouse=True)
def _reset_response_cache():
    # The opt-in response cache is process-global too — a hit left over from
    # one test would silently short-circuit routing in the next.
    from app.response_cache import reset as reset_cache

    reset_cache()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_ledger():
    # Same reasoning as the routing-state and response-cache resets above:
    # per-minute counts and learned ceilings are process-global.
    from app.rate_ledger import reset as reset_ledger

    reset_ledger()
    yield
