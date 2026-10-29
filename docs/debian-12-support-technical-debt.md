# Debian 12 Support Technical Debt

## Summary

Supporting both Debian 12-era Flask / Flask-SQLAlchemy / SQLAlchemy behavior and
the Debian 13 package line at the same time imposes a disproportionate
engineering cost on this repository.

That cost shows up most clearly in the test harness and upgrade path:

- isolation logic becomes harder to trust
- route-test performance is pulled down by compatibility bridges
- modern ORM cleanup is slowed by having to preserve older execution patterns
- the codebase accumulates compatibility-specific complexity that is not part of
  the product itself

Debian stable is now 13. While some test machines may still be on Debian 12, the
technical direction should target Debian 13 package versions rather than
continuing to optimize for a cross-version state that has become expensive to
maintain.

## Recommendation

Drop Debian 12 compatibility as an active goal for this upgrade effort and
target Debian 13 package versions directly:

- Flask 3.1.x
- Flask-SQLAlchemy 3.1.x
- SQLAlchemy 2.0.x
- Werkzeug 3.1.x

This should also unlock a cleaner test strategy:

- restore transaction isolation where it is trustworthy
- remove compatibility shims whose only purpose is older stack behavior
- fully adopt modern SQLAlchemy / Flask APIs rather than preserving transitional
  patterns

## Why Debian 12 Support Became Too Expensive

### 1. Test isolation correctness became harder to guarantee

The old transaction-based isolation fixture was fast, but its correctness relied
on assumptions that became weaker once the repository had to support newer Flask
and SQLAlchemy behavior at the same time:

- Flask-SQLAlchemy 3 scopes more behavior to the active app context
- SQLAlchemy 2 is stricter about session and declarative usage
- request-driven route tests exercise more lifecycle boundaries than pure unit
  tests

Under that mixed-version burden, the fixture was no longer obviously the true
boundary for all database reads and writes. A fast isolation strategy that
cannot be trusted is worse than a slower one.

### 2. Route tests were pushed toward a correctness-first fallback

To keep route tests correct on the newer stack while compatibility constraints
remained, the harness moved to a more blunt strategy: refresh the seeded route
database from a template clone rather than relying on a long-lived transaction
wrapper around SQL-seeded state.

That bridge has advantages:

- easier to reason about
- closer to real seeded schema state
- less dependent on ORM/session internals across versions

But it also has clear costs:

- slower than rollback-based isolation
- heavier database churn
- poorer ergonomics for same-scope parallel workers if they share one mutable
  target database

This is acceptable as a temporary correctness bridge. It is not the end state we
should optimize around.

### 3. Cross-version support slows adoption of the modern ORM style

The repository is already paying the migration cost to:

- use explicit `Mapped[...]` annotations
- move away from legacy `Query` APIs
- align local pins with the newer package line

Keeping Debian 12 compatibility active means each modernization step must be
filtered through an extra question:

"Is this the clean SQLAlchemy 2 / Flask 3 solution, or is this the cleanest
solution that still preserves older behavior?"

That constraint makes the code less direct and increases review, maintenance,
and testing cost.

### 4. Performance work becomes harder to justify

Transaction isolation in tests has real value:

- much faster reset cost
- less database churn
- better developer feedback loops

But recovering those benefits broadly while older-version compatibility remains
active would require more complexity in exactly the most fragile area:

- app-context lifecycle management
- session rebinding
- savepoint restart semantics
- cross-version session factory behavior

That is the wrong place to spend engineering effort while the version matrix
itself is the source of much of the difficulty.

## Testing Cost Imposed By Debian 12 Compatibility

This compatibility burden is not abstract. It creates direct testing costs.

### Slower route isolation

Instead of confidently using transaction rollback as the common strategy, the
repository has had to rely on route-database refresh behavior that is more
expensive per test.

### More fixture complexity

The harness must reason about:

- route vs non-route tests
- ORM-created schema vs SQL-seeded schema
- context ownership
- session scoping differences across versions
- compatibility shims that should disappear once the older stack is no longer a
  requirement

### Harder parallelization story

If route tests are refreshed from a template clone into one mutable database,
parallel workers need their own target DB names to avoid stepping on one
another. That is manageable, but it is additional complexity created by the
bridge strategy.

### Reduced confidence in optimization work

The older universal transaction wrapper was attractive because it was fast. Once
it stopped being obviously trustworthy across the supported matrix, keeping it
for speed alone would have been the wrong trade.

## Why This Supports A Debian 13 Target

Targeting Debian 13 aligns the upgrade effort with the current stable package
line and removes a large amount of transitional burden.

That gives the repository permission to:

- prefer the clearest SQLAlchemy 2 patterns
- restore transaction isolation in tests where it is now maintainable
- simplify fixture ownership around one app context / one session boundary
- remove compatibility code that only exists for the older stack

In other words, Debian 13 is not just a newer package set. It is the boundary
that lets the repository move from "compatibility bridge" mode to "clean modern
baseline" mode.

## Guidance For The Ongoing Upgrade Effort

The next phase should assume Debian 13 package versions are the target and
should optimize for a clean modern baseline, not mixed-version compromise.

Priority order:

1. Correctness
2. Simplicity of the test harness
3. Restored transaction-based test performance where the boundary is trustworthy
4. Broad modernization of legacy ORM/query usage

The key point is that performance work should come back after the compatibility
burden is reduced, not before.

## Conclusion

Continuing to support Debian 12 in this upgrade has a real and measurable
engineering cost, especially in testing. That cost is now high enough that it
is more rational to target Debian 13 directly than to keep paying for a
cross-version state that complicates correctness, performance, and maintenance
at the same time.
