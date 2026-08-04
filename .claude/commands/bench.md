Run the full logsleuth benchmark suite and report an honest scorecard.

1. Regenerate blind scenarios: `cd bench && python3 gen_bench.py && python3 gen_bench2.py`
2. Analyze each with `python3 -m logsleuth bench/<file> --plain`
3. Grade every report against `bench/bench_truth.md` / `bench/bench2_truth.md`:
   a hit = the named root cause matches the true trigger, not a downstream symptom.
4. If `/tmp/loghub` exists, also run `python3 bench/loghub_ga.py /tmp/loghub`.
5. Report a table: scenario, verdict, and for misses what evidence was missing from
   the pack versus present-but-unused. Do not round numbers up, do not hide misses.
