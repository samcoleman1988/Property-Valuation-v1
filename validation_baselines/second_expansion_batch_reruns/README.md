# Properties #47-52 — Re-run History (Third Expansion Batch)

Per ROADMAP.md's outcome-tracking immutability principle (item 1) and the
precedent set for Property #37: predictions are never silently overwritten.
Both the original and corrected runs are retained.

## Original run — UNTRUSTED for properties #47-52

- Part of: `20260724_202812_baseline_v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting.csv`/`.json`.
- Run spanned 2026-07-24T20:28 to 2026-07-25T08:27 (~12 hours wall-clock).
  Property #46 (Wells Road, Bristol) alone shows `elapsed_seconds=40084.1`
  (~11.1 hours) — a wall-clock artifact of the same class documented for
  Property #37 in the first expansion batch: the host machine went to
  sleep mid-request, and `elapsed_seconds` (wall-clock `time.time()`) kept
  counting through the suspend.
- **Properties #47-52 (n=47 through n=52) all show `elapsed_seconds=0.0`,
  `v1_value=0`, `v2_value=0`, `confidence_label=None`, `credibility=INSUFFICIENT_EVIDENCE`,
  with no error recorded.** This is the exact same signature already
  established as untrustworthy for the original Property #37 run: 0.0s is
  too fast for genuine API calls to have completed, and these six
  properties ran back-to-back immediately after the machine woke from the
  #46 sleep event — consistent with the network stack not having fully
  resumed.
- **Do not use these six results.** Retained in the original CSV/JSON,
  not deleted, so that file remains a complete and honest record of what
  actually happened during that run, including its own failure.

## Corrected re-run (isolated, 2026-07-25) — TRUSTED

Re-run individually, outside the full-suite run, immediately after
identifying the anomaly. All six produced plausible, internally consistent
results with real elapsed times, real comparable counts, and real
evidence-status/confidence outputs:

| n | Property | Elapsed | Fetched/Scored | V1 | V2 | Status | Confidence |
|---|---|---|---|---|---|---|---|
| 47 | Russell Grove, Bristol | 1378.8s | 1000/93 | £820,000 | £973,000 | Usable with caution | Medium |
| 48 | Penn Drive, Frenchay, Bristol | 4726.0s | 998/176 | £523,000 | £572,500 | Usable with caution | Medium |
| 49 | Queensholm Close, Downend, Bristol | 104.6s | 882/246 | £480,000 | £452,500 | Reliable | High |
| 50 | Sandringham Avenue, Downend, Bristol | 97.4s | 882/246 | £480,000 | £429,700 | Usable with caution | Medium |
| 51 | Old Gloucester Road, Hambrook, Bristol | 685.6s | 998/282 | £433,000 | £449,000 | Usable with caution | Medium |
| 52 | Clifton Mews, Bristol | 450.3s | 774/53 | £1,195,000 | £1,032,000 | Usable with caution | Medium |

Note: properties #49 and #50 (Queensholm Close and Sandringham Avenue,
both Downend) show identical `total_fetched`/`total_scored` (882/246) —
expected, since they're in the same postcode sector and pull from a
largely overlapping Land Registry query, not a bug.

## Dataset status

`validate_baseline.py`'s PROPERTIES entries for #47-52 are unchanged (no
in-file annotation added, unlike Property #37, to keep this batch's
documentation consolidated in this one file rather than duplicated across
six inline comments). This file is the authoritative record for these six
properties' trusted values going forward. The original 52-property
baseline CSV/JSON is unmodified — this is documentation layered alongside
it, per the "never silently overwrite" principle.
