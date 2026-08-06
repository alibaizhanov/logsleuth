# Homebrew formula

`logsleuth.rb` is ready to publish. It has no `resource` blocks because logsleuth
declares no dependencies, so the virtualenv Homebrew builds contains exactly one
package.

## Why a personal tap and not homebrew-core

homebrew-core will not accept a project that has not cleared its notability bar
(roughly: 75+ stars, 30+ forks, or 30+ watchers, plus a track record). We are nowhere
near that, and submitting early wastes a maintainer's time and gets the PR closed.

A personal tap works immediately and needs no one's approval:

```
brew tap alibaizhanov/tap
brew install logsleuth
```

Revisit homebrew-core if the project ever clears the bar. Nothing about the formula
below would need to change.

## Publishing it

Homebrew requires the tap to live in a repository named `homebrew-<tap>`, so
`alibaizhanov/tap` means a repo called `homebrew-tap`:

```sh
gh repo create alibaizhanov/homebrew-tap --public \
    --description "Homebrew formulae by alibaizhanov"
git clone https://github.com/alibaizhanov/homebrew-tap
mkdir -p homebrew-tap/Formula
cp packaging/homebrew/logsleuth.rb homebrew-tap/Formula/
cd homebrew-tap && git add . && git commit -m "logsleuth 0.11.0" && git push
```

Then verify on a machine that has Homebrew — this repository's formula has never been
built by `brew` itself, only its test assertions were executed by hand:

```sh
brew tap alibaizhanov/tap
brew install --build-from-source logsleuth
brew test logsleuth
brew audit --strict --online alibaizhanov/tap/logsleuth
```

`brew audit` is the one that matters. It checks style, the URL, the checksum and the
licence, and it will fail loudly if any of them is wrong. Do not announce the tap
before it passes.

## Updating for a new release

Three fields change: the version in the URL, the sha256, and nothing else.

```sh
# after `twine upload`
curl -s https://pypi.org/pypi/logsleuth/json | python3 -c "
import json,sys
d=json.load(sys.stdin); v=d['info']['version']
f=next(f for f in d['releases'][v] if f['packagetype']=='sdist')
print(f'url    \"{f[\"url\"]}\"'); print(f'sha256 \"{f[\"digests\"][\"sha256\"]}\"')"
```

Paste both lines into the formula, commit to the tap, done. Consider adding this to
`.claude/commands/release.md` so it happens on every release rather than drifting a
version behind, which is the usual fate of a tap.

## What the test does, and why it is shaped that way

A formula test must be hermetic — no network, no external services. logsleuth's whole
point is local inference, but a model download in a `brew test` would still be wrong,
so the test uses `--dry-run`, which performs the entire deterministic half (scan,
template mining, rare-event ranking, trend extraction) and prints the evidence pack
without ever contacting a model.

It asserts three things:

- the evidence pack is produced and contains a *rare events* section;
- the once-only `DB_POOL_MAX=4 (was 40)` config line is surfaced — i.e. rarity-based
  ranking actually works, not merely that the binary runs;
- `--health` output does **not** contain that line, which is the property that makes
  the diagnostics safe to paste into a bug report.

The third assertion is the valuable one. It is a privacy claim enforced by a test
rather than by a promise, and it would fail the build if the claim ever stopped being
true.
