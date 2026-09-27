# Phase B local paired experiment (2026-09-27)

Evaluated Factory policy `3.2` at code revision `7b4861352a69a09e72efd3902df46d6a33bbfc09` with SDK/runtime `0.157.1`. The three sequential variants used the same frozen local Git base `3414ff0e396defecfab6a006418ee82443d0772a`: two disjoint, low-risk Python fixes (`clamp.py` and `palindrome.py`). There were no product-repository or remote writes. Reproduce the setup and inspect ignored raw receipts with `scripts/evaluation/phase_b.py` (`--live --variant` is required for a model run). Each variant has a separate state namespace. This is one synthetic pair, not a population estimate.

[Sanitized machine-readable results](phase_b_results.json) contain the state, usage, reviewer findings, and oracle result for each variant without local paths or model transcripts.

| Variant | Controller result | Model turns | Input tokens | Cached input | Output tokens | Workflow seconds | Stronger posthoc oracle |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Phase A: per-slice review + combined review | `BATCH_READY_LOCAL` | 7 | 335,280 | 216,832 | 1,767 | 124.3 | Fail |
| Phase B: deferred slices + combined review | `BLOCKED_BATCH_REVIEW` | 3 | 242,683 | 193,792 | 2,314 | 101.6 | Fail |
| Direct native: one self-reviewed combined task | `COMPLETE_SELF_REVIEWED` | 1 | 76,667 | 43,264 | 1,227 | 39.1 | Pass |

All three variants passed the repository's visible test suite. The initial independent oracle covered casefold expansion (`ßs`) and passed the Phase A and Phase B outputs. The Phase B integration reviewer then found another Unicode defect: `is_palindrome('İ')` returned false. A strengthened, separately recorded oracle with hash `fa0b547e07a3039f0477c353f8f5d1b7b3f26848707bf1723f40c5f62efd2a1e` reproduced that defect in **both** Factory variants; the direct native output passed it. The Phase A reviewer missed it and incorrectly marked its batch ready. Phase B caught it and blocked acceptance. The posthoc oracle supersedes the earlier `quality: PASS` fields in the first two raw assessment receipts.

Completion with the strengthened oracle was 0/1 for Phase A, 0/1 for Phase B, and 1/1 for direct native. Phase A had one unreported defect; Phase B reported and blocked one defect. Direct native used self-review, so it has no independent reviewer finding count.

An earlier pilot namespace (`phase-b-pair-1`) was invalid because the harness ran the combined test suite on each unfinished slice. Another pilot (`phase-b-pair-2`) exposed the `ßs` case and led to stronger visible tests. Neither pilot is included in the table.

**Decision:** Keep review deferral experimental and off by default. It reduced model turns in this one pair, but neither Factory variant met the stronger task oracle, and direct native completed with fewer turns and tokens. There is no demonstrated quality non-inferiority or end-to-end efficiency advantage. Further promotion requires stronger task/oracle coverage and more representative paired cases. Cached input is a subset of input tokens, not an additional quantity; serving model identity and currency cost were not observable.
