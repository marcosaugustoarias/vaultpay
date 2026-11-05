"""Domain layer (DDD): pure business model, no FastAPI, no SQLAlchemy, no I/O.

Bounded contexts (see docs/DDD.md):

* ``ledger``   - Core domain. Money, account numbers, transfer rules, risk policy.
* identity     - Supporting. Users, credentials, MFA, sessions (``app.services.auth/mfa``).
* audit        - Generic. Hash-chained evidence log (``app.services.audit``).

Only the Ledger context has been extracted into an explicit domain model so far; the
others still live in ``app.services`` (documented as a conscious, incremental choice).

Rule of the layer: modules under ``app.domain`` may import only the standard library and
other ``app.domain`` modules. ``tests/unit/test_domain_purity.py`` enforces it.
"""
