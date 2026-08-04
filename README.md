# loglens

**Local AI root-cause analysis for production logs. Nothing leaves your machine.**

Feed it an incident's worth of logs — gigabytes are fine — and get back a structured
root-cause report: symptom, timeline, hypothesis with cited evidence, ruled-out red
herrings, next steps. All inference runs locally via [Ollama](https://ollama.com), so
you can use it on logs you'd never paste into a cloud AI: they're full of PII, tokens
and internal hostnames, and your security team knows it.

```
$ loglens incident.log

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
- **It reads *all* of it.** A deterministic preprocessor crunches the full file —
  deduplicates error patterns, computes numeric trends (heap, latency, disk, queue
  depths), finds deploys/migrations/flag flips, detects error concentration by
  node/pod/build — and hands the model a dense evidence pack. No more guessing which
  10KB of a 2GB log to paste into a chatbot.
- **It distrusts loud noise.** Patterns present since the start of the file are
  flagged as baseline; the report explicitly lists red herrings it *didn't* blame.
- **Honest by design.** The model is instructed to cite only real lines and to say
  "insufficient evidence" rather than invent a story.

## Benchmark

10 blind scenarios (written after the code was frozen, generators included in
[`bench/`](bench/)): Kafka rebalance storms, expired TLS certs, clock skew, cache
evictions after a config change, backup-window IO saturation, connection leaks,
third-party rate limiting, NFS-stalled thread pools, bad canaries, flapping
health checks.

**Result: 8/10 correct root causes** with `qwen3:8b` on a MacBook M1 Pro (16GB),
~80 seconds per analysis. The two misses stopped one causal hop short of the true
root cause (named the saturated resource, not what saturated it). Reproduce it
yourself: `python bench/run_bench.py`.

## Install

```bash
pipx install loglens          # or: pip install loglens
ollama pull qwen3:8b          # one-time, ~5GB
loglens /var/log/app/incident.log
```

No other dependencies — pure stdlib.

## Usage

```bash
loglens incident.log                  # analyze a file
kubectl logs deploy/api | loglens -   # or pipe anything into it
loglens incident.log --json           # machine-readable output
loglens incident.log --dry-run        # show the evidence pack, prove nothing else is sent
loglens incident.log --model qwen3:14b  # bigger machine, smarter analysis
```

`--dry-run` prints exactly what would be passed to the local model — audit it, then
`grep` your favorite secret to confirm it's not there.

## Choosing a model

| Your machine | Model | Notes |
|---|---|---|
| 8GB RAM | `qwen3:4b` | fast, decent |
| 16GB RAM | `qwen3:8b` | **default**, benchmark numbers above |
| 32GB+ RAM | `qwen3:14b` / `qwen3:32b` | noticeably deeper analysis |
| On-prem server | anything Ollama serves | point `LOGLENS_OLLAMA_URL` at it |

## How it works

```
raw logs ──► deterministic preprocessor ──► evidence pack ──► local LLM ──► report
             (dedup, trends, changes,        (~25KB max)       (Ollama)
              dimensions, context windows)
```

The preprocessor is the point: local 8B models are good analysts but bad readers of
2GB files. loglens does the reading with boring, auditable code and saves the model
for the part it's actually good at — causal reasoning over dense evidence.

## Roadmap

- [ ] Deeper causal-chain analysis (the 2/10 benchmark misses)
- [ ] `loglens-8b`: a fine-tuned model distilled from thousands of incident analyses
- [ ] Watch mode / webhook: auto-analyze on alert
- [ ] Team features: shared incident history, PagerDuty/Opsgenie integration

## License

MIT
