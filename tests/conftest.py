"""Tests are hermetic: no live DB or providers.

The docker-compose service loads the real DATABASE_URL from .env; if the tests
inherit it they hit the production database (registered agents flip /v1 and
/admin into protected mode, and the DB registry replaces the YAML fixtures).
Dropping the variable before app modules import makes every storage call fail
fast, exercising the same fallbacks a DB outage does.
"""

import os

os.environ.pop("DATABASE_URL", None)
