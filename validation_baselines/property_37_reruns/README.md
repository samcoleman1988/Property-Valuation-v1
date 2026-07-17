# Property #37 (Pipers Close, Heswall, CH60 7RE) — Re-run History

Per ROADMAP.md's outcome-tracking immutability principle (item 1): predictions
are never silently overwritten. Both runs below are retained.

## Run 1 (original) — UNTRUSTED, retained for audit only

- Part of: `20260715_194932_baseline_v2-evidence-status-fallback-guard-real-hpi-cr1-h0_item2-expansion-37.csv`/`.json`, row n=37.
- Result: `elapsed_seconds=0.0`, `v1_value=0`, `v2_value=0`, `error=None`, credibility=`INSUFFICIENT_EVIDENCE`.
- **Do not use this result.** It was flagged immediately as untrustworthy: 0.0s
  is too fast for genuine API calls to have completed, and this was the very
  first property to run after the host machine woke from an overnight sleep
  that occurred mid-run (see property #36's 36,714s elapsed in the same run —
  a confirmed wall-clock artifact of the same sleep event). Most likely
  explanation: the network stack had not fully resumed when this property ran.
- Retained here, not deleted, so the original run's CSV/JSON stay a complete
  and honest record of what actually happened during that run — including its
  own failure.

## Run 2 (corrected re-run, isolated) — TRUSTED

- Run in isolation, 2026-07-16, after the geocoding dedupe/batching fix
  (ROADMAP.md, geocoding fix validation section) was implemented and validated.
- `elapsed_seconds=194.5`, `total_fetched=216`, `total_scored=49`
- `v1_value=300000`, `v2_value=199700`, `v2_confidence_label=Medium (47)`,
  `v2_status=Usable with caution`
- `warnings: EPC floor area matched for 43/49 comparables`
- This run shows normal, plausible timing and non-zero, internally consistent
  values — treated as the trustworthy result for property #37 going forward.
- Note: V2's fair value (£199,700) is well below the £850,000 asking price for
  what Rightmove listed as a 5-bed detached bungalow with agent-claimed
  extension potential. This is a large gap worth a closer look in a future
  session (possibly related to `normalise_property_type()` mapping "bungalow"
  to the "D" (Detached) Land Registry code, pulling in a broad detached-house
  comparable pool rather than bungalow-specific comparables) — flagged here,
  not investigated further, since this task's scope was re-running the
  property, not diagnosing a new valuation question.

## Dataset status

`validate_baseline.py`'s PROPERTIES entry #37 has been annotated (see its
`expected_challenge` field) pointing back to this file. The original CSV/JSON
baseline file is unmodified — this is documentation layered alongside it, per
the instruction not to silently overwrite.
