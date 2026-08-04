# logsleuth

**Local AI root-cause analysis for production logs. Nothing leaves your machine.**

Feed it an incident's worth of logs — gigabytes are fine — and get back a structured
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

Two blind benchmark sets, both in [`bench/`](bench/) with generators and ground
truth. Every scenario was written *after* the code was frozen, so nothing is
tuned to the answers. Reproduce with `python bench/run_bench.py`.

**Set 1 — 10 common failures** (Kafka rebalance storms, expired TLS certs, clock
skew, cache evictions after a config change, backup-window IO saturation,
connection leaks, third-party rate limiting, NFS-stalled thread pools, bad
canaries, flapping health checks): **10/10 correct root causes.**

**Set 2 — 9 harder failures**, most requiring a 2–3 hop causal chain (a poison-pill
message stuck at one offset, inode exhaustion with 412GB free, a DST-repeated cron
run, an upstream contract change, a hot shard, CPU throttling after a pod
reschedule, humongous-allocation GC thrash, split brain, config drift):
**6/9 correct.** The 3 misses name the right component but stop one causal hop
short of the trigger.

Measured with `qwen3:8b` on a MacBook M1 Pro (16GB), ~80s per analysis. Bigger
models do better; that's a one-flag change.


## Install

```bash
pipx install logsleuth       # or: pip install logsleuth   (installs the `logsleuth` command)
ollama pull qwen3:8b          # one-time, ~5GB
logsleuth /var/log/app/incident.log
```

No other dependencies — pure stdlib.


## Output

In a terminal you get a visual report: an **incident map** (error density across
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
