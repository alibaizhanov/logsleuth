---
layout: default
title: logsleuth
description: >-
  Root-cause analysis that reads the whole log file, locally. Notes and measurements
  from building it.
permalink: /
---

<h1>logsleuth</h1>

<p class="subtitle">Root-cause analysis that reads the whole log file, locally.</p>

Point it at an incident and it scans the entire file — 2 million lines in 12.6 seconds
using 61MB of RAM — then reports a root cause with the actual log lines as evidence,
and what it deliberately ruled out. The reasoning runs on a local model, so nothing
you analyze leaves the machine.

```
brew install alibaizhanov/tap/logsleuth
logsleuth demo
```

[Source, benchmarks and how every number was measured →](https://github.com/alibaizhanov/logsleuth)

## Writing

**[The loudest service is never the broken one](/logsleuth/loudest-service/)**
Every counting heuristic for finding the faulty microservice scores 0 out of 30 on an
annotated benchmark — worse than chance. Why error volume points at victims rather
than causes, what to rank by instead, and the feature I deleted after measuring it.
