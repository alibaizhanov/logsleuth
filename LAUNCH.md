# Launch kit

Working notes, not a public document. Everything here follows one rule the research
was unambiguous about: **do not lead with "AI".** Roughly thirty local-AI-log-analysis
CLIs launched in 2025–26 leading with "AI"; none passed 60 GitHub stars and most are
abandoned. In the same window `lnav` — a deterministic log viewer with no AI at all —
took 335 points on HN, and the liveliest thread under it was about memory use on large
files. The audience rewards a fast honest reader. Lead with that; the model is an
implementation detail.

Second rule: **every number stated in public must be reproducible from this repo**, and
two numbers measuring different things must never be mixed into one sentence. The scan
throughput on a raw log file and the throughput of the benchmark harness (which also
parses CSV and scores groups) differ by 40%; quoting one next to the other invites a
reader to divide and catch us. Quote the one the user actually experiences.
The audience punishes unverifiable claims hard — a competing tool's launch was taken
apart in the comments over an unaudited "SOC 2 compliant" badge until the author
retracted it. Everything below is scored by a script anyone can run.

---

## 1. Show HN

**Timing.** Sunday ~19:00 US Eastern (Monday 00:00 UTC). Highest observed success rate
for reaching 50+ points. The half-life of a Show HN is about 24 hours, so be at the
keyboard for the following morning — answering comments matters more than the post.

**Title** — the measurable claim, no "AI", no adjectives:

> Show HN: Logsleuth – the service with the most errors is the culprit 0 times out of 30

Alternate, if the above reads too much like a riddle:

> Show HN: Local root-cause analysis that reads the whole log file (2M lines in 12.6s)

**Body:**

---

I kept losing time in incidents the same way: `grep ERROR`, get two hundred hits,
scroll, and eventually notice the one INFO line above them that actually mattered.

So I built logsleuth. You point it at a log file and it prints a root cause with the
real log lines as evidence, plus what it deliberately didn't blame. The reasoning runs
on a local model via Ollama — nothing leaves the machine.

The part I think is actually interesting isn't the model, it's what happens before it.

While building the benchmark I measured the obvious heuristics on RCAEval, an academic
benchmark of 30 real microservice failures with an annotated culprit service. "Blame
the service with the most error lines" gets it right **0 out of 30**. So does "most
errors in the ten minutes after the fault." So does over-representation versus baseline
traffic. Chance is 2.6/30 — there are 11-13 services — so every counting heuristic does worse
than guessing.

The reason is structural: the service screaming loudest is almost always the caller
that timed out waiting, not the one that broke. Median share of error lines coming
from the actually-faulty service is 10%.

So logsleuth ranks by rarity and position instead of volume — a deploy line that
appears once, shortly before the first new error, outranks ten thousand timeouts. It
scores 17/30 on that set, strictly (the right service must be named in the first
sentence — no credit for mentioning it further down). For calibration, a paper published this year reports 52.31% Recall@1 on the
same benchmark using distributed traces and a frontier model; logsleuth reads logs only,
on a local 8B.

Other numbers, all reproducible from the repo:

- 79.3% grouping accuracy on Loghub-2.0 (13 systems, 39M human-annotated lines)
- 2,057,642 lines (272MB) scanned in 12.6s using 61MB of RAM — memory does not grow with file size
- 132 public corpora scanned with zero failures, zero tracebacks on adversarial input
- blind scenario set: 10/10, and stable — three independent runs gave the same verdict every time

Install is `pipx install logsleuth`, then `logsleuth demo`. First run offers to set up
local inference for you (~5GB model download); if you already run Ollama it uses yours
and downloads nothing.

To check the privacy claim rather than trust it: `logsleuth incident.log --dry-run`
prints the exact text that would be sent to the model. Grep it for your secrets.

Honest limits: on multi-service cascades it names the right service 17 times out of 30
— good relative to the alternatives above, not good in absolute terms, and I'd rather
say so than have you find out at 3am. It reads logs only, so failures that are invisible
in logs (swap thrashing, a saturated NIC) are invisible to it. And it's a single-player
CLI: it does nothing for the coordination cost of a twelve-person incident channel.

Repo: https://github.com/alibaizhanov/logsleuth

---

**Do not** put "AI-powered" in the title. **Do not** claim an MTTR reduction — that
audience knows the VOID research showing MTTR is high-variance, low-fidelity data, and
the claim reads as vendor noise.

---

## 2. The standalone post

This travels independently of the tool and is the higher-leverage artifact. ripgrep
launched off a benchmark write-up, not a feature list.

**Title:** *The loudest service is never the broken one*

**Shape:**

1. The setup — a cascade where five services scream and one is at fault.
2. The measurement — RCAEval, 30 annotated failures, and the table:

   | rule | correct |
   |---|---|
   | most error lines | 0/30 |
   | most errors in 10 min after injection | 0/30 |
   | highest over-representation vs baseline | 0/30 |
   | random guess (expected value) | 2.6/30 |

3. Why every counting rule fails: the loudest is the caller that timed out. Median
   share of error lines from the true culprit is 10%. The upper bound is 30/30 — the
   faulty service *does* log errors in every case, so the task is solvable, just not
   by counting.
4. What does work: rarity and position. A once-only line shortly before the first new
   error beats ten thousand repetitions of a symptom.
5. The part that makes it credible: I shipped a lift-based heuristic that ranked
   over-represented dimensions, then measured it at 0/30 and deleted it. The commit is
   in the repo.
6. One paragraph at the end pointing at the tool.

Post to: r/devops, r/sre, lobste.rs. This is content, not a launch, so it is welcome
where a product post would not be.

---

## 3. Reddit

**r/LocalLLaMA** — highest-intent audience for "runs on your machine". Lead with the
local-model angle *here specifically*, because that is what they came for. Mention the
model auto-sizing (4b under 10GB RAM, 8b under 24GB, 14b above) and that it reuses an
existing Ollama install.

**r/devops and r/sre** — post the standalone article, not the tool. Title as the
finding. Answer questions; do not pitch.

**r/selfhosted** — the air-gapped angle, framed as "works with no network at all".

Read each subreddit's self-promotion rules first. r/sre in particular is unforgiving.

---

## 4. Homebrew

262 million formula installs a year and we ship pip only. This is the cheapest unclaimed
distribution channel we have.

The formula is written and its assertions verified by hand: `packaging/homebrew/`.
It has never been built by `brew` itself — this machine has no Homebrew — so before
announcing the tap anywhere, run `brew audit --strict --online` on a machine that
does. homebrew-core is not an option yet (notability bar); a personal tap works
immediately and needs nobody's approval.

---

## 5. Answers to the questions that will actually be asked

These are the real objections, taken from comment threads under comparable launches.
Answer them plainly. Conceding a limit costs nothing and buys the rest of the argument.

**"How well do LLMs actually do this? Every one I've tried only works on toy examples."**
The most common objection in the category, and fair. That's why the benchmark numbers
are in the README rather than a claim of accuracy: 10/10 on blind single-service
scenarios, 6/9 on harder multi-hop ones, 17/30 strict on RCAEval microservice cascades
where every counting baseline scores 0/30. Run `bench/rcaeval_run.py` and check. The
honest summary: reliable on one service, gives you a direction on a cascade.

**"I can already paste my logs into Claude or ChatGPT."**
If you can, do — it's free and already open. Two cases where you can't: the file is
2GB and you'd be choosing 200 lines to paste, which is the actual hard part of the job;
or your logs contain customer data and someone has forbidden it. If neither applies,
this tool is not for you and I'd rather say so.

**"How do I know it isn't inventing log lines?"**
The model is instructed to cite only lines present in the evidence, and every quoted
line is in your file — grep for it. The evidence pack itself is printable with
`--dry-run`. It can still misattribute a cause; it should not be able to fabricate a
line, and if you find one, that's a bug I want to see.

**"Confidently wrong is worse than saying nothing."**
Agreed, and this shaped the output format. Every report has a *Ruled out* section
saying what was deliberately not blamed and why, a stated confidence level, and the
model is instructed that "insufficient evidence" is a valid answer. On our small-model
run one scenario returned exactly that instead of guessing, and I count that as the
correct behaviour, not a miss.

**"How is the privacy claim enforced?"**
It isn't enforced by a policy, it's enforced by there being no network code path to a
remote model. `--dry-run` shows the whole prompt. Unplug the network and it still works.
There is no telemetry of any kind — which is also why the benchmarks are large and
public, since I get no feedback signal from users to correct with.

**"Does it handle my format?"**
JSON lines, logfmt, plain text, gzip, Kubernetes CRI and Docker envelopes, and a dozen
timestamp formats. Measured on 132 public corpora: all parse without error, 87% have
timestamps recognised. If yours doesn't, `--health` prints diagnostics containing **no
log content**, so you can send it without leaking anything.

**"Why not just use k8sgpt / HolmesGPT / Datadog?"**
Different shape. Those need a cluster or a platform already ingesting your telemetry.
This takes a file — including one someone scp'd off a box an hour ago — and needs no
infrastructure at all.

**"Is it going to stay free?"**
The CLI is MIT and stays that way.

---

## Checklist before posting

- [ ] `logsleuth demo` works from a clean `pipx install` on a machine with no Ollama
- [ ] every number in the post traces to a script in `bench/`
- [ ] README first screen leads with the measurable claim, not "AI"
- [ ] GitHub repo description and topics updated to match
- [ ] the standalone post is published first, so the Show HN can link to it
- [ ] free for the following 24 hours to answer comments
