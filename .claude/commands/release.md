Release a new logsleuth version. Argument: the version number (e.g. 0.8.0).

1. Bump the version in BOTH `logsleuth/__init__.py` and `pyproject.toml`.
2. Smoke test: `python3 -m logsleuth demo --dry-run` and one full `--plain` run.
3. Update README if user-facing behavior changed — measured numbers only, no adjectives.
4. `rm -rf dist && python3 -m build -q && python3 -m twine upload dist/*`
5. Commit with a message stating what changed and the measurement that backs it,
   then push, and tag `vX.Y.Z`.
6. Update the Homebrew tap, or it silently drifts a version behind — which is the
   usual fate of a tap. Print the two lines that change:

       curl -s https://pypi.org/pypi/logsleuth/json | python3 -c "
       import json,sys
       d=json.load(sys.stdin); v=d['info']['version']
       f=next(f for f in d['releases'][v] if f['packagetype']=='sdist')
       print(f'url    \"{f[\"url\"]}\"'); print(f'sha256 \"{f[\"digests\"][\"sha256\"]}\"')"

   Paste both into `Formula/logsleuth.rb` in `alibaizhanov/homebrew-tap`, then
   `brew audit --strict --online` before pushing. Keep `packaging/homebrew/logsleuth.rb`
   in this repo in sync so the two never disagree.
