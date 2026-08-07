# logsleuth

**Root-cause analysis that reads the whole log file, not the 200 lines you pasted.**

Point it at an incident. It scans the entire file — **2 million lines in 12.6 seconds
using 61MB of RAM**, so a 2GB log costs the same memory as a 2MB one — works out what
is actually new, and reports a root cause with the real log lines as evidence, plus
what it deliberately ruled out.

The reasoning runs on a local model, so nothing leaves your machine. You can check
that claim yourself in ten seconds: `logsleuth incident.log --dry-run` prints the
exact text that would reach the model. Grep it for your secrets.

```
$ logsleuth incident.log

## Root cause hypothesis
PostgreSQL connection pool size reduction (from 50 to 10) during deployment.
Confidence: High.
- Deployment log explicitly sets PG_POOL_MAX=10 (line 1316)
- "pg pool timeout" errors start immediately after the deployment
- Latency grew from 56.9ms to 217.9ms (x3.8), idle connections dropped to 0

## Ruled out
- "healthz" noise present before the incident — baseline, not cause
...
```

## Why

- **The loudest component is almost never the broken one.** This is the whole reason
  the tool exists. On 30 annotated microservice failures, "blame the service with the
  most error lines" gets the answer right **0 times out of 30** — worse than picking at
  random — because the service screaming loudest is the caller that timed out waiting,
  not the one that broke. logsleuth ranks by *rarity and position*, not by volume, and
  scores 17/30 on the same set. Numbers and method in [Benchmarks](#benchmarks).
- **Your logs never leave the machine.** No API keys, no cloud, no data processing
  agreements, no argument with the CISO. Works air-gapped.
- **Reads the formats you actually have.** JSON lines, logfmt, plain text —
  sniffed automatically. Timestamps in ISO, syslog, Apache and epoch form all
  parse. Java/Python stack traces fold into the event they belong to instead of
  polluting the analysis as fifty separate lines. Structured fields (`level`,
  `pod`, `latency_ms`) are used directly, and dimensions are picked by
  cardinality — no hardcoded field list.
- **Built for real log sizes.** Streaming, parallel, bounded memory: the file is
  read once in byte-range chunks across CPU cores and only aggregates are kept, so
  a 2GB log costs the same RAM as a 2MB one. (Measured on an M1 Pro: 2,057,642 lines
  / 272MB in 12.6s using 61MB of RAM.)
- **It never shows you a traceback.** Binary files, broken archives, a directory,
  UTF-16, a 20MB line with no newlines, 60k distinct lines, no timestamps at all —
  each gets a plain sentence explaining the problem. When something unexpected does
  break, the message tells you to run `logsleuth --health <file>`, which prints
  parse diagnostics — counts, formats, line *shapes* — with **no log content**, so
  you can attach it to an issue without leaking anything.
- **Verified on 132 real public corpora.** Every LogHub dataset, full size —
  including HDFS (1.6GB, 11.2M lines, scanned in 37s) and BGL (4.7M lines) — plus
  Spark, OpenStack, Android, Apache, syslog and Kubernetes container logs.
  Zero failures, peak memory 28MB regardless of file size, timestamps parsed on
  87% of corpora. `bench/corpus_sweep.py` reproduces the whole table.
- **Fits how logs actually live.** Kubernetes CRI lines (`<ts> stdout F …`) and
  Docker JSON envelopes are unwrapped to the application line underneath;
  gzipped rotated archives open directly; several files merge chronologically.
- **Analyze a moment, not a file.** `--last 30m` / `--since` / `--until` binary-search
  the window by byte offset, so a 30-minute slice of a huge log is read in
  milliseconds — measured: 400k lines, 7.5s for the whole file vs **0.24s** for the
  last 2 hours, skipping 99% of it. Unsorted files fall back to filtering, with a notice.
- **Templates learned, not guessed.** Line grouping uses a Drain-style parse tree
  (ours, pure stdlib): variable parts are found *positionally* — block ids,
  hostnames, usernames, paths — instead of matching a list of "looks like data"
  regexes. Measured on [Loghub-2.0](https://github.com/logpai/loghub-2.0) — 13 real
  systems, **39 million lines**, human-annotated: **79.3% grouping accuracy**.
  `bench/loghub2_ga.py` reproduces it.
- **No keyword lists to maintain.** State changes are found *structurally*: a
  deploy, an eviction or a leader switch is a near-unique line in a file where
  normal operation repeats thousands of times. Rare + shortly-before-the-first-error
  = prime suspect, in any stack, any vendor, any phrasing.
- **It reads *all* of it.** A deterministic preprocessor crunches the full file —
  deduplicates error patterns, computes numeric trends (heap, latency, disk, queue
  depths), finds deploys/migrations/flag flips, detects error concentration by
  node/pod/build — and hands the model a dense evidence pack. No more guessing which
  10KB of a 2GB log to paste into a chatbot.
- **It distrusts loud noise.** Patterns present since the start of the file are
  flagged as baseline; the report explicitly lists red herrings it *didn't* blame.
- **Honest by design.** The model is instructed to cite only real lines and to say
  "insufficient evidence" rather than invent a story.

## Benchmarks

Three benchmark sets, all reproducible from this repo.

**RCAEval** — third-party academic benchmark ([Pham et al.](https://github.com/phamquiluan/RCAEval)),
30 real Sock Shop failure cases with an annotated root-cause service, ~85k log lines each:
**17/30 (57%) correct service localization**, scored strictly — the right service must be named
in the *first sentence* of the root cause, not merely mentioned somewhere (67% by the looser rule).

That number reads low until you see what it is beating. Running the same 30 cases through
simple rules, with no model involved at all (`bench/rcaeval_ceiling.py`):

| method | correct |
|---|---|
| service with the most error lines | 0/30 |
| most error lines in the 10 min after fault injection | 0/30 |
| highest error over-representation vs. baseline traffic | 0/30 |
| pick a service at random (expected value) | 2.6/30 |
| **logsleuth** | **17/30** |

Every count-based heuristic scores zero because in a microservice cascade the loudest service
is the caller that timed out, not the one that broke — the median share of error lines coming
from the actually-faulty service is 10%. The upper bound is 30/30: the faulty service does emit
error lines in every case, so the task is solvable from logs, just not by counting.

Note logsleuth reads *only logs*, while RCAEval is built for methods that also consume metrics
and traces. `bench/rcaeval_run.py` reproduces the run.

**Loghub-2.0** — 13 real systems, 39 million annotated lines. This is the benchmark the
ISSTA'24 study ["How Far Are We?"](https://github.com/logpai/loghub-2.0) built after showing
that the older 2,000-line LogHub flatters every parser; on full-size data accuracy drops
sharply and most parsers cannot finish at all — only 6 of 15 completed within 12 hours.

| | |
|---|---|
| grouping accuracy | **79.3%** (74.9% before enum-aware templates) |
| throughput | 39M lines scored in 5.6 minutes end-to-end (CSV parse + match + score) |

`bench/loghub2_ga.py` reproduces it. The older 2k benchmark is kept as `bench/loghub_ga.py`
for continuity (79.1%), but the number above is the one that predicts behaviour on a real file.

**Blind synthetic sets** — scenarios written *after* the code was frozen, so nothing is tuned
to the answers. Set 1 (10 common failures): **10/10**, and stable — three independent runs
gave the same verdict every time. Set 2 (10 harder, 2-3 causal hops): **5/10** with the local
8B model; every miss names a real symptom but stops one hop short of what caused it.

The interesting part is what happens when a *frontier* model reads the same evidence pack:
**10/10**, including all five the local model missed. So the pack carries the answer and the
small model cannot always extract it — which is why the MCP server hands the pack to your
agent rather than reasoning for it. Packs and scoring are reproducible from `bench/`.

Measured with `qwen3:8b` on a MacBook M1 Pro (16GB). On `qwen3:4b` — what we auto-select on
machines under 10GB of RAM — set 1 scores 9/10, and the tenth is an honest "insufficient
evidence" rather than a wrong answer. Bigger models do better; that's a one-flag change.


## Install

```bash
brew install alibaizhanov/tap/logsleuth   # or: pipx install logsleuth
logsleuth demo
```

That is the whole install. On first run logsleuth asks once before setting up local
inference, then does it for you:

```
logsleuth runs the model on this machine, so your logs never leave it.
  It needs a local runtime (0.1GB) and the model qwen3:8b (5.2GB).
  Both go in ~/.logsleuth and can be deleted later.
  Set this up now? [Y/n]
```

Nothing is installed system-wide and nothing needs `sudo`; `rm -rf ~/.logsleuth` undoes it.
If you already run Ollama, logsleuth uses it as-is — including whatever model you already
have pulled, so there is nothing to download at all. Add `--yes` for unattended setup.

The model is picked to fit your machine: `qwen3:4b` under 10GB of RAM, `qwen3:8b` under 24GB,
`qwen3:14b` above that. Override any of it with `--model` or `LOGSLEUTH_MODEL`.

No Python dependencies — pure stdlib.


## Use it from an AI agent

An agent that hits a 2GB log has no good move: it reads the first few hundred lines or
greps blindly, then reasons about whatever it happened to see. That is not fixed by a
bigger model — the file is larger than any context window.

logsleuth ships an MCP server that hands the agent an evidence pack instead. Measured
on a 208MB log: **1.6M lines read in 9.1s using 58MB of RAM, returned as 12KB** — a
17,000x reduction that keeps the parts carrying the answer rather than the parts that
happen to come first.

```json
{
  "mcpServers": {
    "logsleuth": { "command": "logsleuth-mcp" }
  }
}
```

Three tools: `read_log_evidence` (the whole file, or a `--last 30m` style window),
`inspect_log_file` (cheap sanity check before committing a turn to it), and
`log_parse_diagnostics` (format diagnostics containing no log content).

No model runs in the server — the agent is the model, and usually a better one than
the local qwen3 the CLI uses. The server's job is to make the file legible.

## Output

The report leads with the answer — root cause first, with quoted evidence — so you can stop
reading as soon as you have what you need. In a terminal you also get a visual header: an **incident map** (error density across
the file, with deploy/config markers), **trend sparklines** (latency, memory,
queue depths), and color-coded sections with confidence badges. Piped or with
`--plain` it degrades to clean markdown; `--json` for machines.

```
 INCIDENT MAP (error density across the file)
   ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▃▅▄▅▅▄▄▅▆▇▅▆▆▆▆▆▆▆▆▆▆▆▇▆▇▆▆███
                 ▼                               ▼ = deploy/config/migration

 TRENDS
   ▼ idle 28→0                    ██████▄▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁
   ▲ latency 57→218ms             ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁██▇███▁▁▁▁▁
```

## Usage

```bash
logsleuth demo                        # try it right now on a bundled sample incident
logsleuth app.log --last 30m          # only the last 30 minutes (seeks, does not read the rest)
logsleuth app.log --since 03:00 --until 04:00
kubectl logs deploy/api --since=1h | logsleuth -   # k8s CRI format is unwrapped automatically
logsleuth app.log.2.gz                # rotated archives work as-is
logsleuth app.log --health            # parse diagnostics only, safe to share
logsleuth incident.log                # analyze a file
logsleuth api.log db.log gateway.log  # merge services chronologically; source becomes a dimension
kubectl logs deploy/api | logsleuth -  # or pipe anything into it
logsleuth incident.log --json         # machine-readable output
logsleuth incident.log --dry-run      # show the evidence pack, prove nothing else is sent
logsleuth incident.log --model qwen3:14b  # bigger machine, smarter analysis
```

`--dry-run` prints exactly what would be passed to the local model — audit it, then
`grep` your favorite secret to confirm it's not there.

Every command, plus how to run the benchmarks and cut a release, is in
[RUNBOOK.md](RUNBOOK.md).

## Choosing a model

Picked automatically from your RAM, so this table is only for overriding it.

| Your machine | Model | Notes |
|---|---|---|
| under 10GB RAM | `qwen3:4b` | auto-selected; fast, decent |
| 10–24GB RAM | `qwen3:8b` | auto-selected; benchmark numbers above |
| 24GB+ RAM | `qwen3:14b` / `qwen3:32b` | auto-selected; noticeably deeper analysis |
| On-prem server | anything Ollama serves | point `LOGSLEUTH_OLLAMA_URL` at it |

## How it works

```
raw logs ──► deterministic preprocessor ──► evidence pack ──► local LLM ──► report
             (dedup, trends, changes,        (~25KB max)       (Ollama)
              dimensions, context windows)
```

The preprocessor is the point: local 8B models are good analysts but bad readers of
2GB files. logsleuth does the reading with boring, auditable code and saves the model
for the part it's actually good at — causal reasoning over dense evidence.

## Roadmap

- [ ] Deeper causal-chain analysis (the 2/10 benchmark misses)
- [ ] `logsleuth-8b`: a fine-tuned model distilled from thousands of incident analyses
- [ ] Watch mode / webhook: auto-analyze on alert
- [ ] Team features: shared incident history, PagerDuty/Opsgenie integration

## License

MIT
