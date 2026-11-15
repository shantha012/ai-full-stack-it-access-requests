# Access request review queue

Python CLI for extracting source facts and preparing human review. No output approves or provisions access.

Setup from the repository root (Python 3.10+, uv; tested Python 3.12.3 and uv 0.13.7):

```bash
UV_CACHE_DIR=/tmp/access-uv-cache uv sync --frozen
source .venv/bin/activate
env -u API_KEY python3 -m unittest discover -s tests -v
```

To run tests without activating the virtual environment, use:

```bash
UV_CACHE_DIR=/tmp/access-uv-cache uv run --frozen --offline env -u API_KEY python3 -m unittest discover -s tests -v
```

Run the setup command first. A bare `python3` outside the activated environment may use the system Python, which does not have the project's dependencies (including `jsonschema`) installed. `env -u API_KEY` removes the API key; it does not select a Python environment or install dependencies.

Install separately from running tests. The fresh-install test uses `uv sync --frozen --offline` with the populated `/tmp/access-uv-cache` cache; the first setup needs registry access. All new saved replies are under `test/mock_responses/`; the supplied starter fixture remains under `tests/mock_responses/`. Tests use saved replies/fake HTTP, temporary state, and blocked sockets. No test reads an operator API_KEY or calls a live model. T25 supplies a dummy key through an isolated mapping.

Run the exact mock walkthrough below from the repository root after activation. It leaves 20 original documents in the main queue and the authored paraphrase in a separate database. Each command explicitly selects mock responses. The injected failure is recorded, then retried; its earlier success remains in attempts.

<!-- offline-walkthrough -->
```bash
python -m access_requests --provider mock intake materials/requests
python -m access_requests --provider mock queue
python -m access_requests --provider mock queue --pending
python -m access_requests --provider mock attempts IT-001.json --pending
python -m access_requests --provider mock resume
python -m access_requests --provider mock retry IT-001.json --mock-reply unavailable
python -m access_requests --provider mock queue
python -m access_requests --provider mock retry IT-001.json --mock-reply it-001
python -m access_requests --provider mock refresh IT-001.json
python -m access_requests --db state/paraphrase.sqlite --provider mock intake tests/fixtures/IT-021.json
python -m access_requests --db state/paraphrase.sqlite --provider mock export --output state/paraphrase-output
python -m access_requests --provider mock accuracy --extra-records state/paraphrase-output/extractions.jsonl --output state/accuracy.md > state/accuracy.json
python -m access_requests --provider mock export
```

Inspect `status`, `owner`, and `next_action`: IT-001 is `review / System Owner / review-request`; IT-010 is `needs-information / IT Service Desk / clarify`; during the injected failure IT-001 is `error / IT Service Desk / retry-extraction`. IT-006 goes to `review / IT Service Desk / inspect-message`. Pending views label completed records with their own earlier attempt, source hash, settings, and policy; unfinished jobs have their separate identity and state.

`--db`, `--provider`, `--mock-dir`, `--workers`, `--lease-seconds`, `--model`, `--endpoint`, `--timeout`, `--max-output-tokens`, `--prompt-file`, `--schema-file`, and `--policy-file` precede the subcommand. Paths may be individual exports or flat directories. Mock replies are fixed by filename in `corpus-replies.json`; missing saved replies fail explicitly. Retry/refresh optionally accept `--mock-reply NAME` for an explicit scripted outcome. Ordinary unchanged successes and failures are reused; retry/refresh bypass reuse. Changed bytes or producing settings create a new generation and preserve history. Later batches retain omitted documents.

For a separately authorized live run, set `API_KEY` in the environment and explicitly select `--provider openai`, preferably with a separate `--db state/live.sqlite`. The implemented provider is OpenAI's non-streaming Responses endpoint, default model `gpt-4.1-mini-2025-04-14`, timeout 30 seconds, maximum output 2048 tokens. Model, endpoint and request budget are configurable. Instructions and user source are separate; strict JSON Schema output is validated after completion/refusal checks. See [official Responses documentation](https://developers.openai.com/api/reference/resources/responses/methods/create) and [model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini). Credentials never enter stored settings, error payloads, logs, or request evidence. No live run was performed during implementation. Q-49 remains open: failed real attempts currently identify the configured provider/model as the attempted origin, not as proof that a model produced a response.

SQLite with JSON1 (tested SQLite 3.45.1) sharing supports overlapping processes on one POSIX host and local filesystem. Use the same database and output destination; no multi-host/NFS or Windows guarantee is made. Default workers: 4, capped at 32. Jobs commit before calls; expired claims are reclaimable with `resume`. Default leases exceed the configured request timeout by 30 seconds. If killed, wait for lease expiry before resuming. An uncertain/crashed call can be repeated; calls are not exactly-once. The last registered source generation wins, including when an older call completes later. A later failed retry becomes the current error; prior successes remain in history.

`export` creates an immutable directory and atomically switches the `deliverables` symlink. Readers must resolve that link **once** and read both files from that resolved directory. Exporters serialize publication with a brief SQLite write reservation and filesystem lock. Each linked row includes snapshot generation, attempt, hash, settings, and policy. A crash may leave an unreferenced directory; the previous or new complete snapshot remains readable. Git preserves the relative symlink and committed generation. Archive tools must preserve symlinks or dereference the resolved directory once.

Accuracy compares 12 exact scalar fields across the 20 exports plus the separately authored paraphrase: denominator 252. Missing/failed records keep 12 cells. Reference purpose spans (21 cells) and IT-006 permission (one cell) remain unresolved pending Q-21/Q-54/Q-29; there is no finalized full-corpus score. Mock results establish repeatable plumbing, not live extraction accuracy. Frozen facts and source references are in `tests/fixtures/expectations.json` and `planning/plan.md`. `reports/accuracy.md` and the exported report disclose each observation's configuration/origin. The live model remains responsible for extraction; corrections, conflicts, relative dates and new permissions in mock tests demonstrate integration with saved facts.

The functional workload test uses exactly 2,000 authored messages, two processes, a blocked first message, and bounded workers. It checks progress/history/coherence with mocks; it establishes no live throughput, cost or latency SLA. Inputs are flat UTF-8 JSON exports with a string `message` and unique basenames. Nested topologies, unsupported export versions, malformed exports and messages beyond the stated 200-word range are outside the verified scope. Incomplete-withdrawal and unsupported-fact/evidence policy classifications await Q-31/Q-32; schema validation is not factual verification. Routing detects the supplied override marker or an extracted override issue; it is not a general injection detector.

`reports/` holds reproducible handover artifacts copied into each export; `deliverables/` holds the committed example snapshot. See `deliverables/verification.md`, `planning/evidence/S01-red.txt` through `S15-red.txt`, the corresponding full-suite green logs, and `planning/test-run.txt` for observed checks. Entire creates session checkpoints automatically on commits. Session acceptance, remote default-branch publication, and assignment submission remain pending C04–C06 and facilitator instructions. This build does not push or submit.
