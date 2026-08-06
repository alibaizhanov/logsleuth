# The loudest service is never the broken one

*A measurement, and what it did to a tool I was building.*

---

Here is a shape every on-call engineer knows.

Something breaks at 3am. You open the logs and five services are screaming. The
gateway is throwing 502s. The order service is timing out. The queue worker is
retrying in a loop. The frontend is logging failed upstream calls by the hundred.
Somewhere in that noise is the one service that actually broke, and the other four
are just downstream of it, complaining loudly about being kept waiting.

The obvious move is to follow the noise. Whichever service is producing the most
errors is probably where the problem is.

I built that heuristic into a log-analysis tool. Then I measured it, and it turns out
to be not just imperfect but **completely, reliably wrong**.

## The measurement

[RCAEval](https://github.com/phamquiluan/RCAEval) is an academic benchmark from a
WWW'25 paper. It contains real failure cases from a running microservice system —
faults were injected into a specific service, everything was recorded, and the
culprit is annotated. The subset I used has 30 cases, each about 85,000 log lines
across thirteen services.

Because the answer is known for every case, you can score any rule you like without
a model, a heuristic, or an opinion getting in the way. So I scored the obvious ones.

| rule | correct |
|---|---|
| blame the service with the most error lines | **0 / 30** |
| blame the service with the most errors in the 10 min after the fault | **0 / 30** |
| blame the service whose errors are most over-represented vs. its normal traffic | **0 / 30** |
| pick a service at random | 2 / 30 |

Read that table again. Every counting rule scores **zero**, and random guessing beats
all of them.

That is a stronger result than "the heuristic is unreliable." A rule that was merely
useless would land near random. Scoring zero across thirty independent cases means
the rule is *anti-correlated* with the truth — it is actively pointing away from the
answer. In this benchmark, "most errors" reliably names an innocent service. You
would do better flipping a coin, and much better asking your least experienced
colleague.

Two more numbers make the picture concrete:

- **The median share of error lines coming from the actually-faulty service is 10%.**
  Nine tenths of the noise is produced by its victims.
- **The faulty service does emit error lines in all 30 cases.** The ceiling is 30/30.
  The task is entirely solvable from the logs. It just is not solvable by counting.

## Why counting fails

Once you see it, it is obvious, and the obviousness is the trap.

Consider a database connection pool that has been misconfigured to a tenth of its
former size. What does the database service log? Almost nothing. It is answering
queries normally; there are simply fewer connections available. Perhaps one line
recording the configuration change.

Now consider everything upstream. Every request that cannot get a connection times
out. Every timeout triggers a retry. Every retry occupies a worker. The workers run
out, so the service ahead of *that* starts timing out, and it retries too. Within a
minute you have four services in a retry storm producing tens of thousands of error
lines between them, and the service that actually broke has logged **one line**.

The volume of errors a component produces measures **how much it depends on the
broken thing**, not how broken it is. The loudest component is, structurally, the one
with the most retries and the shortest timeouts — a property of its client
configuration, not of its health.

This is why over-representation doesn't rescue you either. The third rule in the table
is more sophisticated than raw counting: it compares each service's share of errors
against its share of normal traffic, so a service that is simply busy cannot dominate.
That is the statistically respectable version of the idea, and it is the version I
reached for when the naive one looked crude. It also scores 0/30 — because the problem
was never that the counting was too coarse. Error volume points at victims, and
normalising a victim signal leaves you with a well-normalised victim signal.

## What I did about it

I deleted the heuristic. Both versions of it.

The first version shipped. Release 0.9.0 put a line in every report reading something
like *"service: 83% of all error-like lines have service=X"*, and handed it to a
language model as a hint. That is worse than useless: it is a confident-sounding
pointer aimed at an innocent service, delivered to something whose job is to be
persuaded by pointers.

The second version never made it out, and only because I measured first. I had already
written the more sophisticated replacement — the over-representation ranking, dividing
each service's error share by its traffic share — and I liked it. It corrected the
obvious flaw in the first version. It is the thing I would have defended in a review.
It also scores 0/30, which I only know because the benchmark existed before the
release did.

What replaced it is not another ranking. The distribution is still reported, as a
plain fact, with an explicit note attached:

> *(distribution only: the component logging the most errors is commonly a victim of
> the failure, not its cause)*

The numbers are evidence. The verdict they seemed to support was a lie, so the verdict
is gone.

## What does work

If volume is the wrong signal, what is the right one?

**Rarity and position.** In a log file where normal operation repeats thousands of
times, the interesting events are the ones that happen *once*. A deployment finishing.
A configuration value being applied. A leader election. A cron job starting. A
certificate being loaded. These lines are almost always `INFO`, almost always
unremarkable, and almost always the thing you wish you had noticed first.

So instead of ranking by how often a line appears, rank by how *rarely* it appears —
and boost lines that occur shortly before the first genuinely new error in the file.
A single line that appears once, thirty seconds before the error pattern that was
never seen before, outranks ten thousand timeouts.

That is the entire idea, and it needs no keyword list. I do not need to know that
`pg_basebackup` is a backup, or that `PG_POOL_MAX` is a pool size, or that this
particular company calls its deploys "rollouts". I need to know that the line is
nearly unique in a file where everything else repeats, and that it sits just before
the trouble started. That property is the same in every stack, every vendor, and
every language.

On the same 30 RCAEval cases, ranking this way scores **17/30**. That is not a
triumphant number, and I want to be careful about how it is read: it means that on a
multi-service cascade the tool gives you a direction rather than a diagnosis. But the
comparison that matters is the table at the top of this post. Against 0/30 for every
counting rule and 2/30 for chance, it is the difference between a hint and an
anti-hint.

## The part I actually want you to take away

I am not writing this because my tool scores well. I am writing it because of what
happened when I measured.

I had a rule that was intuitive, defensible, and the sort of thing you would nod along
to in a design review. *Errors concentrate where the problem is* — of course they do.
It survived because it sounded right and because nothing in the system was set up to
contradict it. Building the benchmark took considerably longer than building the
feature, and the benchmark's first useful act was to delete the feature.

There is a version of this essay that ends with a lesson about measurement, and it
would be true but too comfortable. Here is the sharper version: **the reason this rule
survived so long is that it fails in exactly the way that is hardest to notice.** It
does not produce nonsense. It confidently names a service that really is, at that
moment, full of errors. Everything about the output looks correct. If you are on call
at 3am and a tool tells you that the service currently drowning in timeouts is the
problem, you will believe it, because it agrees with what you are already seeing on
your dashboard.

An answer that is wrong and obviously wrong costs you nothing. An answer that is wrong
and *plausible* costs you the whole incident.

---

*The tool is [logsleuth](https://github.com/alibaizhanov/logsleuth) — it reads a log
file end to end, locally, and reports a root cause with the actual log lines as
evidence. Every number in this post is reproducible from that repository:
`bench/rcaeval_ceiling.py` scores the baselines and the ceiling with no model
involved, and `bench/rcaeval_run.py` scores the tool. If you rerun them and get
something different, I would like to know.*
