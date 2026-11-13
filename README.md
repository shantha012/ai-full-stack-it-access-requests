# Access request review queue

This CLI prepares Northstar access messages for human review. It preserves source
bytes, validates model replies, and applies the ordered office policy. Managers
are contacts; reviewers make approval decisions.

## Setup

Use Python 3.10 or later, from the repository root. Python 3.11 is the runtime
verified here. Create a virtual environment and install the complete pinned set:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.lock
```

The CLI uses the standard library plus jsonschema; requirements.lock pins its
transitive dependencies. The local verification environment already contained
these exact versions. A fresh package download/install was not exercised here;
this environment's existing virtual environment does not include pip. A normal
Python installation with venv/ensurepip is needed for the setup commands above.

## Reproducible mock workflow

Run these commands in order from the repository root. No credentials are needed.
The first database has the 20 originals; the separate accuracy database also
includes the independently authored paraphrase. Repeating intake reuses unchanged
results; `retry` explicitly makes a new attempt from retained source bytes.

```sh
python3 -m access_requests intake --db work/intake.sqlite --mocks tests/mock_responses materials/requests
python3 -m access_requests queue --db work/intake.sqlite
python3 -m access_requests history --db work/intake.sqlite --document IT-001.json
python3 -m access_requests retry --db work/intake.sqlite --document IT-001.json
python3 -m access_requests resume --db work/intake.sqlite
python3 -m access_requests export --db work/intake.sqlite --output work/current
python3 -m access_requests intake --db work/accuracy.sqlite --mocks tests/mock_responses materials/requests tests/inputs/SYN-001.json
python3 -m access_requests export --db work/accuracy.sqlite --output work/accuracy
python3 -m access_requests accuracy --db work/accuracy.sqlite --extractions work/accuracy/extractions.jsonl --expected tests/expected --output work/accuracy.md
```

`queue` may run in another terminal while intake is working. Each completed record
is visible immediately, and other records show `pending` or `running` with attempt
and source IDs. A new pending revision replaces the current pointer; consult
`history` for a prior completed result. Files omitted from later batches remain.

`export` publishes completed current records only. Pending/running entries remain
inspectable in `queue`. Concurrent export readers should read `CURRENT` once,
then open both files in the named immutable generation directory. The portable
`extractions.jsonl` and `queue.json` copies are for completed exports; copying two
files is not atomic. History remains in SQLite, outside current export files.

## Tests and accuracy

```bash
env -u API_KEY python3 -m unittest discover -s tests
```

Tests use saved responses in tests/mock_responses and source-authored expectations
in tests/expected. Plan cases block network calls and API_KEY reads, including
subprocesses. HTTP tests inject a fake transport and a non-secret sentinel. No
test uses a live model. T43 executes the documented CLI workflow in a temporary
copy; it checks installed lockfile versions rather than downloading dependencies
or recursively running the full suite.

Committed deliverables/extractions.jsonl and queue.json contain 20 mock records.
Accuracy observations additionally contain SYN-001. Reproduce the committed
report without extraction using:

```bash
python3 -m access_requests accuracy --db work/report.sqlite --extractions deliverables/accuracy-observations.jsonl --expected tests/expected --output work/reproduced-accuracy.md
```

The mock comparison is 231/231 non-purpose scalar matches and 21/21 reference
purpose sentences. Nulls count; missing keys fail. Purpose wording is scored
separately without normalization. Exact evidence substrings and issue concepts
are checked outside that denominator. These results measure the local pipeline
and comparator, not live model accuracy. See deliverables/accuracy.md for the
source messages, expected facts, policy quotes, settings and negative control.

## Optional provider integration

The implemented HTTP adapter supports the Chat Completions JSON envelope:
`choices[0].finish_reason`, `message.refusal`, and JSON in `message.content`.
It sends `messages` with the policy and schema in the system role, keeps source
text in a separate user role, and requests strict json_schema output. The
configured default model is `gpt-4o-mini`, temperature 0, timeout 30 seconds,
endpoint `https://api.openai.com/v1/chat/completions`. Actual model access and
endpoint compatibility were not verified live. Select a model/endpoint supporting
this contract. Credentials are loaded from the environment variable `API_KEY`
only when the HTTP adapter is invoked; do not place credentials in CLI arguments.

```bash
python3 -m access_requests intake --db work/provider.sqlite --provider http --model gpt-4o-mini --endpoint https://api.openai.com/v1/chat/completions --timeout 30 --workers 4 materials/requests
```

The adapter accepts endpoint/model/timeout through CLI flags; temperature and
transport are constructor settings. There are no other application environment
variables. Tests alone use `TEST_CONTROL` for process barriers. Only endpoint URLs
without embedded credentials or credential query parameters are supported.

Refusal and any non-stop finish reason fail before JSON parsing. JSON/schema and
exact source-quote validation precede routing. Errors yield null extraction and
IT Service Desk / retry-extraction, with a command carrying the database and
document ID. Inspect source and diagnostics before retrying. History retains any
previous success. Diagnostics omit provider bodies, exception text and credentials.
Request evidence is in deliverables/request-evidence.json, labelled transport-stub.

## Operations and limits

Use a single host and local disk for the shared SQLite database; regional operators
connect to that host. Multi-host or network-filesystem SQLite is outside the
verified scope. Intake defaults to four bounded workers, configurable from 1 to 32.
The context is 200–400 messages daily and bursts around 2,000; no throughput,
latency, disk-capacity or burst-load benchmark was run and no service target is
claimed. Provider requests run outside brief database transactions.

An HTTP 429/503 or transport failure gets at most two retries, with waits of one
and two seconds. Other replies are not automatically retried. Running work holds
a lease sized from the configured timeout and retry budget (128 seconds with the
default 30-second HTTP timeout). After an interruption, run `queue`, then `resume`.
Only expired leases are recovered; completed work is retained and recovered claim
tokens fence stale publishers. Resume processes pending entries sequentially.
A worker that exceeds its lease cannot publish; recover it after expiry. Real
provider calls during a crash/recovery can be repeated and may incur charges.

Identical overlapping inputs share claims. Competing different revisions or
settings are rejected while prior work is unfinished, pending an authoritative
ordering rule; resolve the existing work before submitting the next ordered batch.
The plan also leaves contradictory withdrawals unresolved; current routing follows
the literal withdrawal precedence and has no dedicated test for that ambiguity.

Extraction configuration, prompt/schema fingerprints and routing-policy identity
are retained per attempt. Changed source or extraction configuration re-extracts.
Unchanged completed attempts, including errors, are reused until explicit retry.
The Store API supports a policy-only reroute of a retained valid extraction when
the extraction fingerprint is unchanged; the CLI has no custom policy file flag.
Editing office policy also changes the extraction prompt and therefore re-extracts.

Canned replies cannot establish live extraction fidelity. Scalar source support,
all novel override wording and free-text purpose equivalence need human inspection.
The local override detector recognizes a bounded set of patterns and issue labels.
The source messages remain untrusted data. See deliverables/verification.md for
observed checks, repairs, deferred interpretations and facilitator submission steps.
