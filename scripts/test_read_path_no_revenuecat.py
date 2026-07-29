"""A4 regression guard: the entitlement READ/gating path has ZERO RevenueCat
dependency (write-only invariant).

RevenueCat touches the system in exactly one place: the webhook WRITES the
source (A3). The read path (compute_tier / source_active / gating) reads the
source straight from the LocalStore record and never imports or calls
RevenueCat. That structural separation is what makes "RevenueCat outage ->
existing entitlements intact" true.

The guard blocks ANY revenuecat-named module on the read path (the webhook
`app.api.v1.revenuecat` AND the pure `app.utils.revenuecat_mapping`) -- the read
path stays entirely IAP-write-free by design. It catches DIRECT static imports
of the READ_PATH_MODULES below (add new gate modules there); dynamic imports
(`__import__`/`importlib`) and transitive couplings are out of scope.

This test is PURE: the static check AST-parses files (no import -> no app boot);
the behavioral check imports only app.utils.entitlements (pure stdlib). No
data/content.json or seed_output is read.
"""
import sys
import os
import ast
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The entitlement READ path: projection (compute_tier/source_active) + the gate
# (is_premium) + the backlog gate (delegates to gating). Write-path modules
# (billing.py, revenuecat.py) are intentionally NOT listed.
READ_PATH_MODULES = [
    "app/utils/entitlements.py",   # compute_tier / source_active -- the projection read
    "app/utils/gating.py",         # is_premium -- the gate
    "app/utils/backlog.py",        # backlog gate (delegates to gating)
]


def _imported_names(relpath):
    """All module references an import statement introduces, fully qualified.

    For `from app.api.v1 import revenuecat` this yields both the source module
    (`app.api.v1`) AND the bound name as a dotted path (`app.api.v1.revenuecat`)
    -- so a `from <pkg> import revenuecat` is caught, not just
    `import <pkg>.revenuecat`. Without the dotted form the guard would be
    vacuous against the most natural way to import the webhook module.
    """
    tree = ast.parse(open(os.path.join(ROOT, relpath)).read())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.module:
                names.add(n.module)
                for a in n.names:
                    names.add(f"{n.module}.{a.name}")
            else:
                for a in n.names:
                    names.add(a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                names.add(a.name)
    return names


def test_read_path_modules_never_import_revenuecat():
    for mod in READ_PATH_MODULES:
        imports = _imported_names(mod)
        offenders = [m for m in imports if "revenuecat" in m]
        assert not offenders, f"{mod} imports RevenueCat ({offenders}) -- read path must stay RevenueCat-free"


NOW = datetime(2026, 6, 25, tzinfo=timezone.utc)
FUT = (NOW + timedelta(days=10)).isoformat()
PAST = (NOW - timedelta(days=10)).isoformat()


def test_compute_tier_serves_apple_source_without_revenuecat():
    # Imported inside the test so the static guard stays independent of the
    # import chain (app.utils.entitlements is pure stdlib; no app boot).
    from app.utils.entitlements import compute_tier
    assert compute_tier({"entitlements": {"apple": {"status": "active", "expires": FUT}}}, NOW) == "premium"
    assert compute_tier({"entitlements": {"google": {"status": "active", "expires": FUT}}}, NOW) == "premium"
    assert compute_tier({"entitlements": {"apple": {"status": "expired", "expires": PAST}}}, NOW) == "free"
    # No revenuecat module is needed to read entitlement -- proven by this
    # passing with only app.utils.entitlements imported.
