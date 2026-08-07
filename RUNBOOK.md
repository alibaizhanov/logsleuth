# Runbook

Every command for this project in one place: using it, developing it, measuring it,
releasing it. Written so a step can be executed without reconstructing the reasoning
behind it — the reasoning lives in `CLAUDE.md`.

Working directory is `~/Projects/loglens`; the package is `logsleuth`.

---

## Using it

```sh
logsleuth demo                         # bundled sample incident, no setup needed
logsleuth incident.log                 # analyze a file
logsleuth app.log --last 30m           # only the last window; seeks, does not read the rest
logsleuth app.log --since 02:00 --until 02:10
logsleuth app.log.2.gz                 # rotated archives open directly
logsleuth api.log db.log gw.log        # merge services chronologically; source becomes a dimension
kubectl logs deploy/api --since=1h | logsleuth -    # CRI/Docker envelopes unwrapped
logsleuth app.log --json               # machine-readable
logsleuth app.log --plain              # no colors or graphs
logsleuth app.log --dry-run            # print the evidence pack, run no model
logsleuth app.log --health             # parse diagnostics, contains NO log content
logsleuth app.log --model qwen3:14b    # override the auto-chosen model
logsleuth app.log --yes                # unattended first-run setup
```

`--dry-run` is the privacy check: it prints exactly what would reach the model, so
`logsleuth x.log --dry-run | grep -i secret` settles the question rather than trusting it.

## Using it from an agent (MCP)

```sh
logsleuth-mcp                          # JSON-RPC 2.0 over stdio; stdout is protocol only
```

Register it — `.mcp.json` in this repo already does this for Claude Code:

```json
{ "mcpServers": { "logsleuth": { "command": "logsleuth-mcp" } } }
```

Tools: `read_log_evidence` (whole file or a window), `inspect_log_file` (cheap sanity
check), `log_parse_diagnostics` (format diagnostics, no content). No model runs in the
server.

Exercise it by hand without an agent:

```sh
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_log_evidence","arguments":{"path":"bench/bench_05.log"}}}' \
 | logsleuth-mcp | python3 -m json.tool --json-lines
```

## Installing

```sh
brew install alibaizhanov/tap/logsleuth        # macOS/Linux, includes logsleuth-mcp
pipx install logsleuth                         # or pip
pip install -e .                               # from a clone, for development
```

---

## Measuring

Never tune against a scenario you are looking at. Write new blind scenarios *after*
freezing the code, then measure.

```sh
# Grouping accuracy on 39M annotated lines — the number that matters (79.3%)
python3 bench/loghub2_ga.py /tmp/loghub2
python3 bench/loghub2_ga.py /tmp/loghub2 --only Apache,Proxifier   # quick subset

# The old 2k benchmark, kept for continuity only (79.1%)
python3 bench/loghub_ga.py /tmp/loghub

# Blind scenario sets: regenerate and analyze
python3 bench/run_bench.py --model qwen3:8b        # set 1, expect 10/10
# grade by comparing bench/bench_report_NN.md against bench/bench_truth.md

# RCAEval: our score (17/30 strict, ~60 min) and the baselines (no model, seconds)
python3 bench/rcaeval_run.py /tmp/re3ss/RE3-SS --model qwen3:8b
python3 bench/rcaeval_ceiling.py /tmp/re3ss/RE3-SS

# Robustness and breadth — run both after ANY change to scan/parse/drain
python3 bench/test_robustness.py                   # expect: 0 tracebacks
python3 bench/corpus_sweep.py /tmp/loghub          # expect: 0 failures
```

### Benchmark data

| set | location | how to get it |
|---|---|---|
| Loghub-2.0 | `/tmp/loghub2` | 14 zips from <https://zenodo.org/record/8275861> (920MB zipped, ~5GB unpacked) |
| LogHub 2k | `/tmp/loghub` | `git clone --depth 1 https://github.com/logpai/loghub` |
| RCAEval RE3-SS | `/tmp/re3ss/RE3-SS` | see <https://github.com/phamquiluan/RCAEval> |

`/tmp` is cleared on reboot, so expect to re-download.

---

## Releasing

Bump both version strings, they must not drift:

```sh
sed -i '' 's/version = "0.12.0"/version = "0.13.0"/' pyproject.toml
sed -i '' 's/__version__ = "0.12.0"/__version__ = "0.13.0"/' logsleuth/__init__.py
```

Then, in order — do not skip the smoke tests, a broken release cannot be recalled:

```sh
python3 -m logsleuth demo --dry-run              # deterministic half
python3 -m logsleuth demo --plain                # full run, ~80s
python3 bench/test_robustness.py                 # 0 tracebacks
python3 bench/corpus_sweep.py /tmp/loghub        # 0 failures

rm -rf dist build *.egg-info && python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*                   # credentials in ~/.pypirc

git add -A && git commit && git push origin main
git tag -a v0.13.0 -m "v0.13.0: what changed" && git push origin v0.13.0
```

Verify from a clean environment, not from the source tree:

```sh
V=/tmp/relcheck && rm -rf $V && python3 -m venv $V
$V/bin/pip install --no-cache-dir "logsleuth==0.13.0"
$V/bin/logsleuth --version
$V/bin/pip list --format=freeze | grep -v "^pip\|^setuptools\|^wheel"   # must be logsleuth only
```

### Then the Homebrew tap, or it silently drifts a version behind

```sh
# print the two lines that change
curl -s https://pypi.org/pypi/logsleuth/json | python3 -c "
import json,sys
d=json.load(sys.stdin); v=d['info']['version']
f=next(f for f in d['releases'][v] if f['packagetype']=='sdist')
print(f'url    \"{f[\"url\"]}\"'); print(f'sha256 \"{f[\"digests\"][\"sha256\"]}\"')"
```

Paste both into **two** files — they must agree:
`packaging/homebrew/logsleuth.rb` and `~/Projects/homebrew-tap/Formula/logsleuth.rb`.

```sh
cd ~/Projects/homebrew-tap && git add -A && git commit -m "logsleuth 0.13.0" && git push

brew update                                      # brew audits its LOCAL tap copy
brew audit --strict --online alibaizhanov/tap/logsleuth   # must exit 0
brew upgrade alibaizhanov/tap/logsleuth
brew test alibaizhanov/tap/logsleuth                      # must exit 0
```

`brew` lives at `/opt/homebrew/bin` and may not be on `PATH` in every shell;
`export PATH="/opt/homebrew/bin:$PATH"` first if `brew` is not found.

---

## The MCP registry

The official registry feeds the downstream MCP directories, so publishing there once
propagates; there is no per-directory submission to do.

```sh
mcp-publisher validate                 # checks server.json against the live schema
mcp-publisher login github             # interactive; the io.github.alibaizhanov/ namespace
mcp-publisher publish
```

Ownership of the PyPI package is proven by the string `mcp-name:
io.github.alibaizhanov/logsleuth` appearing in the package description, which is
README.md. **Do not remove that comment from the top of the README** — publishing is
rejected without it, and the failure does not say why in an obvious way.

`server.json` must track the released version: bump `version` and
`packages[0].version` together with the two version strings above, or the registry
records a version that does not exist on PyPI.

## The website

`docs/` is served as GitHub Pages via `.github/workflows/pages.yml`.

```sh
gh workflow run pages.yml --repo alibaizhanov/logsleuth      # rebuild and deploy
gh run list --repo alibaizhanov/logsleuth --limit 3          # watch it
curl -sI https://alibaizhanov.github.io/logsleuth/loudest-service/ | head -1
```

If a deploy hangs in `deployment_in_progress` until timeout, the Pages backend has a
stuck record and no API call clears it — cancelling, deleting the run, deleting the
environment and deleting the site all leave the same deployment ID in place. Wait it
out and re-dispatch. The article stays readable meanwhile at
`github.com/alibaizhanov/logsleuth/blob/main/docs/loudest-service.md`.

---

## Where things are

| what | where |
|---|---|
| design decisions, measured dead ends | `CLAUDE.md` |
| launch texts, FAQ, channels | `LAUNCH.md` |
| the write-up | `docs/loudest-service.md` |
| Homebrew formula (mirror of the tap) | `packaging/homebrew/` |
| per-case RCAEval verdicts | `bench/rcaeval_results_30.json` |
| tap repo | `~/Projects/homebrew-tap` |

Read `CLAUDE.md` before changing `scan.py`, `drain.py` or the prompt — it records
several changes that looked obviously right and measured worse, with the numbers.
