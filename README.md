# logsleuth

**Local AI root-cause analysis for production logs. Nothing leaves your machine.**

Feed it an incident's worth of logs — gigabytes really are fine: 183MB scans in
**3 seconds across your cores using 21MB of RAM** — and get back a structured
root-cause report: symptom, timeline, hypothesis with cited evidence, ruled-out red
herrings, next steps. All inference runs locally via [Ollama](https://ollama.com), so
you can use it on logs you'd never paste into a cloud AI: they're full of PII, tokens
and internal hostnames, and your security team knows it.

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
  a 2GB log costs the same RAM as a 2MB one. (Measured: 2M lines in 3.1s / 21MB on
  an M1 Pro; a naive in-memory pass took 29s and 788MB.)
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
  regexes. Measured on [LogHub](https://github.com/logpai/loghub), 16 real
  systems with human-annotated templates: **79.6% grouping accuracy**, up from
  61% before (published parsers land around 86%). `bench/loghub_ga.py` reproduces it.
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
**26/30 (87%) correct service localization**. Note logsleuth reads *only logs*, while RCAEval
is built for methods that also consume metrics and traces. `bench/rcaeval_run.py` reproduces it.

**LogHub** — 16 real systems with human-annotated line templates:
**79.5% grouping accuracy** (was 61% before the Drain-style miner; published parsers land ~86%).
`bench/loghub_ga.py` reproduces it.

**Blind synthetic sets** — scenarios written *after* the code was frozen, so nothing is tuned
to the answers. Set 1 (10 common failures): **10/10**. Set 2 (9 harder, 2-3 causal hops):
**6/9** — the misses name the right component but stop one hop short of the trigger.

Measured with `qwen3:8b` on a MacBook M1 Pro (16GB). Bigger models do better; that's a one-flag change.


## Install

```bash
pipx install logsleuth       # or: pip install logsleuth   (installs the `logsleuth` command)
ollama pull qwen3:8b          # one-time, ~5GB
logsleuth /var/log/app/incident.log
```

No other dependencies — pure stdlib.


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
logsleuth incident.log                # analyze a file
logsleuth api.log db.log gateway.log  # merge services chronologically; source becomes a dimension
kubectl logs deploy/api | logsleuth -  # or pipe anything into it
logsleuth incident.log --json         # machine-readable output
logsleuth incident.log --dry-run      # show the evidence pack, prove nothing else is sent
logsleuth incident.log --model qwen3:14b  # bigger machine, smarter analysis
```

`--dry-run` prints exactly what would be passed to the local model — audit it, then
`grep` your favorite secret to confirm it's not there.

## Choosing a model

| Your machine | Model | Notes |
|---|---|---|
| 8GB RAM | `qwen3:4b` | fast, decent |
| 16GB RAM | `qwen3:8b` | **default**, benchmark numbers above |
| 32GB+ RAM | `qwen3:14b` / `qwen3:32b` | noticeably deeper analysis |
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
