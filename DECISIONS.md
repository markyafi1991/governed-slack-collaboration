---
version: "1.0"
created: 2026-11-13
updated: 2026-11-13
---

# Decisions and limits

**Version 1.0** · 2026-11-13

1. Export the coordinator and offline routing seam. Provider adapters and live
   Slack configuration remain outside this slice, so reproduction needs no key.
2. Allow only one peer handoff. This makes the bound explicit and avoids a
   recursive agent conversation. It is not a general multi-agent scheduler.
3. Validate a handoff before the first send. A malformed peer choice cannot
   produce a misleading lead post. A later peer failure can still leave a
   partial thread; that limit is retained and tested.
4. Record admission before effects. An uncertain send must not trigger automatic
   repeated model calls or messages. The tradeoff is incomplete admitted turns.
5. Distinguish runtime identity, employee role, provider identity and repository
   grants. The synthetic roster demonstrates roles; it supplies no deployment
   credential and proves no employee has any repository or application access.

References: `coordinator.py`, `routing.py`, `demo.py`,
`tests/test_collaboration.py` and `PROVENANCE.json`. No private collaboration
transcripts, operating records or third-party bridge source are reproduced.
