# Approval boundary regression evidence

Observed 2026-11-15, Python CLI with saved mock responses; no live provider call or human approval decision.

Commands from the repository root:

```bash
UV_CACHE_DIR=/tmp/access-uv-cache uv run --frozen --offline env -u API_KEY python3 -m unittest discover -s tests -p test_approval_boundary.py -v
UV_CACHE_DIR=/tmp/access-uv-cache uv run --frozen --offline env -u API_KEY python3 -m unittest discover -s tests -v
git diff --check
```

Targeted: 1 test passed in 1.739s (`approval-boundary-targeted.txt`). Full suite: 41 tests passed in 32.446s (`approval-boundary-full-suite.txt`). No initial failure is claimed: the test protects existing review routing. Existing working-tree changes were retained and are included in this suite run.

T37 checks CLI processing counts, named managers, review routing after reuse/retry/refresh and changed input containing a manager approval claim, retained source history and linked exports. It verifies workflow behavior with saved responses, not live extraction accuracy or reviewer authentication.

C08 manual inspection found separate Intake and Human approval steps in AGENTS.md and README.md. Approval defaults to pending; an explicit decision requires a reviewer, time, document identity/source hash and decision reference. Queue owner/next action and Security Review's recommendation before owner decision are documented. This session's handoff reports test intake and approval separately. This check cannot guarantee future session compliance; the CLI does not persist approval decisions.

Planning consistency check: all 129 requirement IDs occur once in the same order in spec, plan coverage and validation. R-75 maps to S18/T37/C08 in addition to its existing checks. Assessment totals remain 97 met and 32 not met; no unrelated acceptance gaps are closed by this follow-up.
