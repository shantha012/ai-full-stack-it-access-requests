# Verification and handover

## Observed local checks

Runtime: Python 3.11; dependencies match every pin in requirements.lock. All
observations below use saved mock responses or the injected HTTP transport stub.
There were no live provider calls and no measured live model accuracy. Expected
facts were authored from the plan, original messages and policy, not extraction
outputs. Tests block network and API_KEY reads, including CLI subprocesses.

Run from the activated repository environment:

```bash
env -u API_KEY python3 -m unittest discover -s tests
```

The completed suite contains 43 plan cases T01–T43 plus three starter checks
(46 tests). T43 separately executes every CLI command in the README mock workflow
in a clean temporary copy, verifies the 20-record current export and 21-record
accuracy export, and compares request evidence with the implemented adapter.
Dependency verification compares installed package metadata with the lockfile.
Fresh installation is planned for the recipient's environment; it was not run
here because the provided virtual environment lacks pip. Python 3.10 was not run.

| Cases | Intended comparison and observed behavior |
| --- | --- |
| T01–T04 | Saved provider envelopes, byte identity, metadata boundaries, required keys/types/enums, completion and exact decoded quote validation. |
| T05–T25 | Independently expected facts and ordered routes for all 20 originals, paraphrase, missing-field matrix and precedence variants. Mock pipeline checks pass; model fidelity remains unmeasured. |
| T26–T29 | Configured request and schema reach only a stub; errors, refusal and parseable or cut-off incomplete replies yield null extraction and retry guidance. Sentinel credentials are absent from evidence and diagnostics. |
| T30–T34 | Unchanged reuse, changed source revisions, failed retry preserving earlier success, independent documents and settings/policy provenance. Policy-only refresh uses a labelled test policy through the Store API. |
| T35 | Separate-process queue inspection exposes IT-001 completion while IT-002 waits at a controlled barrier. |
| T36 | A provider error for one record leaves the other record moving to Security Review. |
| T37 | Identical overlapping CLI processes share one source attempt and a coherent current record. |
| T38 | A worker is killed; completed work remains, expired work resumes, and an old claim token cannot publish. Lease advancement uses an injected clock. |
| T39 | Injected exceptions before DB commit and export reference switch preserve a coherent prior generation; recovery exposes a matching newer queue/extraction pair. This models crash boundaries, not hardware power loss. |
| T40 | Executing the displayed retry command recovers the source facts. Fake-clock retries wait 1 and 2 seconds, stop after three calls, and keep running state visible. |
| T41 | Twenty current schema-valid exports join their queue by document, attempt and source hash; forced retries remain history rather than duplicate current entries. |
| T42 | Source-derived comparison scores 231/231 scalar fields and 21/21 reference purposes. A saved wrong-date control scores 230/231 and reports the exact mismatch; missing documents/null keys fail. |
| T43 | README workflow executes offline in a clean copy; setup pins, evidence contract and required operating explanations are checked. |

Final observed result on 2026-11-13: `Ran 46 tests in 8.000s` followed by
`OK`; `git diff --check` also passed. T43 passed independently before this suite run. Accuracy details and
all source-derived expected records are in accuracy.md and tests/expected/T05.json
through T25.json. Committed current artifacts are mock observations from the 20
originals; accuracy-observations.jsonl adds the paraphrase. No mock score is a claim
about unseen wording or a live model.

## Observed repairs during the build

Step 9 originally selected T07's named manager for the missing-null-key control.
The original message explicitly names Priya Shah. The test was corrected to remove
T07's null environment field instead; source expectations were not changed. A
subsequent report edit introduced a literal newline escape outside a Python string;
that syntax error was corrected. Both failures stopped work until the user requested
the corresponding repair. Full-suite checks passed after each repair. The starter
mock test's unnecessary API_KEY environment access was removed during Step 10.

## Operating assumptions and limits

One single host with a local SQLite database serves regional operators connecting
to that host. This is not verified for multi-host operation or network filesystems.
The stated workload is 200–400 daily messages, with around 2,000 in a burst; no
load benchmark or latency/capacity guarantee was inferred from those volumes.
Intake has 1–32 workers, four by default; transactions cover claims and publication,
not provider waits. Resume currently runs pending work sequentially.

Intake records pending/running/completed states. Inspection exposes completed work
before the batch finishes. Default HTTP leases last 128 seconds; after a killed
worker, resume recovers only expired leases. Tokens fence stale publication;
already-completed documents survive. Finite rate-limit/transport retries can repeat
provider requests after interruptions. Earlier successes remain in history if a
later attempt fails. Current exports omit pending/running attempts; queue shows them.

Export generations are immutable paired files from one SQLite snapshot. Resolve
CURRENT once for concurrent reads. Portable top-level files describe a completed
export; they cannot be replaced together atomically. Interrupted exports may leave
unreferenced generation or temporary files, with the previous CURRENT still valid.
No cleanup or hardware power-loss test was performed.

Tests cover ordered revisions and identical overlaps. Concurrent different revisions
or configuration changes are rejected while work is unfinished. An authoritative
source ordering rule and contradictory withdrawals remain open interpretations;
no dedicated contradictory-withdrawal expectation is claimed. Literal withdrawal
precedence is implemented. A change to office policy also changes the prompt hash,
so the CLI re-extracts; Store supports policy-only refresh with fixed extraction
settings, tested using an explicit test policy.

Mocks prove local processing, not general natural-language extraction. Novel
instruction overrides, semantic support for every scalar, free-text purpose
equivalence, actual endpoint/model access and service performance require further
inspection. The default configured model is gpt-4o-mini at temperature 0 with a
30-second timeout, and the wire contract is Chat Completions strict JSON schema.
Request-evidence.json records a transport-stub request, with Authorization redacted.
No actual credential was used; endpoints with embedded credentials are unsupported.

## Planned facilitator and submission checks

These remain user/facilitator actions, outside automated completion:

1. Obtain the facilitator's coding-session capture procedure. Entire hooks are
   already configured; pair the recorded session with the exact final submitted
   commit. Local commits alone do not prove the facilitator's capture requirement.
2. Review README, source, lockfile and all required deliverables. Check `git status
   --short` and `git ls-files` so the final application, outputs and capture are
   committed. Local implementation commits were explicitly authorized by the user.
3. Determine the remote default branch and inspect its final commit during release.
   The remote default branch and remote submitted commit were not verified here.
4. After the user authorizes publication, push the final commit and facilitator
   capture to that default branch; verify the remote commit matches the capture.
5. Submit only the repository root URL through Classroom, as the facilitator directs.

No push, Classroom submission or manual Entire checkpoint was performed. R-78,
R-82 and R-83 remain manual release checks. Requirement coverage is described in
planning/plan.md; its planned checks are not independent proof of these release acts.
