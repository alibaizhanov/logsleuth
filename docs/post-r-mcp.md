# r/mcp post

Reddit rules first: check whether the sub requires a flair, forbids links in the body,
or has a karma threshold. Breaking one of those costs a ban, not a warning.

Post as a **text post**, not a link post — the config block is the hook and it has to
be visible without a click.

---

**Title:**

> MCP server for logs that don't fit in context — 208MB → 12KB in 9s, no model in the server

---

**Body:**

Every agent I use has the same blind spot: hand it a log file bigger than its context
and it reads the first few hundred lines, greps around, then reasons confidently about
whatever it happened to see. A bigger model doesn't fix it — the file is just larger
than the window.

So I built an MCP server that reads the whole file and hands back a summary of what
actually happened in it.

```json
{ "mcpServers": { "logsleuth": { "command": "logsleuth-mcp" } } }
```

`brew install alibaizhanov/tap/logsleuth` or `pipx install logsleuth`. Zero
dependencies — pure Python standard library, nothing to pull in.

**Measured on a 208MB log:** 1,576,412 lines read in 9.1s using 58MB of RAM, returned
as 12,646 characters. Memory doesn't grow with file size, so a 2GB log costs the same
as a 2MB one.

**No model runs in the server.** Your agent is the model, and a much better one than
anything I'd run locally. The server's only job is to make the file legible: it's all
deterministic, so nothing leaves the machine and nothing is nondeterministic between
calls.

**Three tools:**

- `read_log_evidence` — the whole file, or a window (`last: "30m"`, or since/until)
- `inspect_log_file` — cheap check before you spend a turn on something that turns out to be a core dump
- `log_parse_diagnostics` — format diagnostics containing zero log content, safe to show a user

**What "12KB" actually contains,** because truncation would be useless: deduplicated
line patterns with how often each occurs and where it first appears; near-unique lines
ranked as candidate state changes; numeric trends across the file; how errors
distribute across service/pod/host; and raw context around where new errors start.

The ranking is by rarity and position, not volume — a config line that appears once,
thirty seconds before the first new error, outranks ten thousand timeouts. That's not
a style choice. On an annotated benchmark of 30 microservice failures, "blame the
service with the most error lines" gets it right **0 times out of 30**, worse than
chance, because the loudest service is the caller that timed out waiting rather than
the one that broke. Write-up with the numbers:
https://alibaizhanov.github.io/logsleuth/loudest-service/

**Limits, so you don't find them at 3am:** logs only — a failure that's invisible in
logs is invisible to this. Timestamps parse on 87% of the 132 public corpora I tested
against, so an exotic format will get you a thinner summary. And it never writes to
the file you point it at — the only thing it ever creates is a temp file when you ask
for a time window, which it deletes afterwards.

MIT, source and every benchmark script: https://github.com/alibaizhanov/logsleuth

Happy to answer anything, and if it produces a bad summary on a log of yours I'd
genuinely like to see it — I have no telemetry, so a report is the only signal I get.

---

## Notes for answering comments

- **"Why not just grep?"** Grep needs a pattern. The useful line in an incident is
  usually one you wouldn't have thought to search for. That's also why there's no
  keyword list anywhere in it — every one I tried had to be deleted later.
- **"Does it work on X format?"** JSON lines, logfmt, plain text, gzip, k8s CRI and
  Docker envelopes. `log_parse_diagnostics` answers this for their file specifically,
  without them sharing content.
- **"Is it actually deterministic?"** Yes — no model, no sampling, no network. Same
  file in, same pack out.
- **"How big can it go?"** Tested to 16.6M lines in a single file. Memory is bounded —
  the scan is streaming and parallel across cores, so RSS does not track file size.
- If someone reports a format that fails, ask for `log_parse_diagnostics` output — it
  carries no log content, so they can paste it safely.
