# logsleuth

Local AI root-cause analysis for production logs. Nothing leaves the machine:
a deterministic scanner builds an evidence pack, a local LLM (Ollama) reasons over it.

Published as `logsleuth` on PyPI and github.com/alibaizhanov/logsleuth.
Note: this working directory is still named `loglens` (pre-rebrand) — the package is `logsleuth`.

## Commands
```bash
python3 -m logsleuth demo               # bundled sample incident
python3 -m logsleuth FILE --dry-run     # print the evidence pack, run no model
python3 bench/loghub2_ga.py /tmp/loghub2 # grouping accuracy, 39M annotated lines
python3 -m build && python3 -m twine upload dist/*   # release (bump version in 2 places first)
```
Ollama lives at `~/Applications/Ollama.app/Contents/Resources/ollama` (no brew, no sudo).
Default model `qwen3:8b`; a full analysis takes ~80s on an M1 Pro.

## Architecture
- `scan.py` — streaming, parallel, bounded-memory scan; byte-range chunks across cores.
  Keeps only aggregates. `build_pack()` turns them into the evidence pack.
- `drain.py` — Drain-style template mining. Variable parts are found *positionally*,
  never by a "looks like data" regex list.
- `parse.py` — format sniffing (json/logfmt/text), multi-format timestamps,
  stack-trace folding, CRI/Docker envelope stripping.
- `window.py` — `--last/--since/--until` via binary search on byte offsets.
- `backend.py` — first-run bootstrap: reuse a running Ollama, else start a found binary,
  else download one into `~/.logsleuth` with consent. Model chosen from available RAM.
- `cli.py` — input resolution, prompt, Ollama streaming. `render.py` — terminal UI.

## Conventions
- Zero runtime dependencies. Pure stdlib, always — it is a selling point.
- Structural over vocabulary: prefer statistics (rarity, position, cardinality) to
  keyword lists. Every keyword list we added had to be replaced later.
- Colors only on a TTY; honor NO_COLOR and TERM=dumb; stdout=result, stderr=status.
- Public files (README, bench truth, comments) are English-only.

## Benchmarks — the feedback loop
Never tune against a scenario you are looking at. Write new blind scenarios *after*
freezing the code, then measure. Current honest numbers:
- `bench/gen_bench.py` (easy, 10 scenarios): 10/10 root causes, and **stable**: three
  independent runs of all ten gave the same verdict every time (30/30). Wording moves
  between runs, the diagnosis does not — so the 10/10 is not a lucky sample. One run in
  twenty produced an empty report and succeeded on retry; worth watching, not yet a bug
  with a reproduction.
- `bench/gen_bench2.py` (hard, 9 valid): 6/9 — misses stop one causal hop short
- **Loghub-2.0 grouping accuracy: 79.3%** over 13 systems / 39M lines at 116k lines/s
  (`bench/loghub2_ga.py`). This is the number to move; the old 2k LogHub (79.1%,
  `bench/loghub_ga.py`) is kept for continuity only — ISSTA'24 showed it flatters
  every parser. Baseline before enum-aware templates was 74.9%.
  Two invariants the miner must keep:
  - `_similarity()` must not count wildcard positions as agreement — doing so let one
    cluster generalize into a catch-all that swallowed every rare line in the file.
  - a wildcard position that only ever held 2 values is an enum, not a variable
    (`_Cluster.seal`). Without it, 8 SOCKS5 lines poisoned a 10,219-line HTTPS
    cluster and Proxifier scored 1%. Swept: 2 values wins, 3+ over-splits.
- Blind set 1 on `qwen3:4b` (auto-selected under 10GB RAM): 9/10; the tenth is an
  honest "insufficient evidence", not a wrong answer. The small-machine path is
  measured, not assumed.
- Loghub-2.0 lives in /tmp/loghub2 (zenodo.org/record/8275861, 920MB of zips, ~5GB
  unpacked). GA scoring must compare group identity, not rebuilt tuples — the
  quadratic version never finishes on BGL/Spark.

### Where we stand versus published work (researched 2026-08-06)
- Our ~50% strict top-1 on RCAEval is **at the level of published SOTA**: RCLAgent
  (multi-agent recursion-of-thought, Claude-3.5-Sonnet backbone) reports 52.31%
  Recall@1 — and it consumes *traces*, while we read logs only with a local 8B.
  Do not describe our number as weak — measured across all 30 it is 57%. Do not lead with it either: incident.io's
  public guidance calls anything under ~70% precision trust-destroying, so the
  honest headline is the deterministic scanner, not the localization rate.
- The measured bottleneck across the field is *reasoning over evidence*, not evidence
  extraction (51.4% of failures are "data was present and misused" vs 1.4% "data
  absent"). More extraction will not help; better-shaped extraction might.
- Multi-hop failure is specifically an **edge** problem: models identify the right
  components (Node F1 62.2%) and fumble the links between them (Edge F1 43.4%).
  That is exactly our 6/9. The fix both research directions converged on: hand the
  model candidate causal *edges* (per-component first-error ordering, lagged
  precedence relations) so edge inference becomes edge selection.
- **Do NOT turn this into a ReAct/tool-calling agent.** 8B-class models fail at
  tool-call syntax, not at reasoning; a structured multi-agent pipeline scored 0.0
  with a small base model where a frontier model scored 25-57%.
- Deep-learning log anomaly detection (DeepLog, LogAnomaly, LogBERT) does not survive
  replication; PCA on template counts matches it at 1/200000th the training cost.
  Classical statistics is the right family for us, and it needs no training data.

### Tried and rejected — do not re-attempt without a new argument
- **LCS variant linking across token-count buckets** (merge "close, 0 bytes sent" with
  "close, 451 bytes (0.4 KB) sent"). Swept 18 strictness settings: best was 79.2% vs
  79.1% without it, i.e. nothing, while re-introducing over-merge risk. OpenStack
  gained 31pp, OpenSSH lost 46pp — it trades one corpus for another.
- **Masking whole timestamps in drain via `parse.TS_COMBINED`.** Sounds obviously right;
  measured worse on raw logs (937 -> 1126 templates over 10 corpora, Mac 321 -> 413).
  Drain buckets by token count, so collapsing a 3-token timestamp to 1 token splits one
  event across buckets whenever the match is not uniform.
- Both were measured on the old 2k benchmark. The "GA ~79% is this architecture's
  plateau" conclusion drawn from them was wrong: enum-aware templates moved
  Loghub-2.0 from 74.9% to 79.3%. The real lesson is that the 2k set was too small
  to show a difference — measure on Loghub-2.0 before concluding anything.
- RCAEval (external, 30 real microservice failures): **17/30 = 57%** service
  localization, scored strictly (named in the first sentence); 20/30 = 67% by the
  looser "mentioned anywhere in the root cause" rule. Measured on all 30 cases —
  the earlier ~50% was extrapolated from a 10-case sample and understated us.
  Breakdown by culprit: orders 8/9, front-end 5/9, carts 4/12. The carts cases are
  where the remaining headroom is — worth reading a few of those logs before
  building anything aimed at multi-hop reasoning. Baselines on the same set are 0/30 for every count-based rule and 2/30 for
  chance, expected value 2.6/30 (`bench/rcaeval_ceiling.py`); ceiling is 30/30. Do not add "the loudest component
  is the culprit" heuristics — that exact rule was measured at 0/30 and removed.
- `bench/corpus_sweep.py` over 132 real corpora: 0 failures, <=28MB RSS, 87% with
  timestamps parsed. Run it after any change to scan.py / parse.py / drain.py.
