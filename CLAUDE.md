# logsleuth

Local AI root-cause analysis for production logs. Nothing leaves the machine:
a deterministic scanner builds an evidence pack, a local LLM (Ollama) reasons over it.

Published as `logsleuth` on PyPI and github.com/alibaizhanov/logsleuth.
Note: this working directory is still named `loglens` (pre-rebrand) — the package is `logsleuth`.

## Commands
```bash
python3 -m logsleuth demo               # bundled sample incident
python3 -m logsleuth FILE --dry-run     # print the evidence pack, run no model
python3 bench/loghub_ga.py /tmp/loghub  # grouping accuracy vs real logs (needs loghub clone)
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
- `bench/gen_bench.py` (easy, 10 scenarios): 10/10 root causes
- `bench/gen_bench2.py` (hard, 9 valid): 6/9 — misses stop one causal hop short
- LogHub grouping accuracy: 79.5% (was 61% before drain.py; published parsers ~86%)
