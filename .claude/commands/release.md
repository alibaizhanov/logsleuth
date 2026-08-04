Release a new logsleuth version. Argument: the version number (e.g. 0.8.0).

1. Bump the version in BOTH `logsleuth/__init__.py` and `pyproject.toml`.
2. Smoke test: `python3 -m logsleuth demo --dry-run` and one full `--plain` run.
3. Update README if user-facing behavior changed — measured numbers only, no adjectives.
4. `rm -rf dist && python3 -m build -q && python3 -m twine upload dist/*`
5. Commit with a message stating what changed and the measurement that backs it,
   then push. Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
