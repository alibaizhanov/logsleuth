bench2_01.log: root cause = a poison-pill message at partition=7 offset=90412 (protobuf truncated varint): the consumer crashes on it, restarts, resumes at the SAME offset and crashes again forever; partition 7 lag never advances while other partitions are fine. Must name the specific stuck offset/poison message and suggest skipping/DLQ, not 'consumer is crashing'.

bench2_02.log: root cause = inode exhaustion on worker-3 /var (inodes_used climbs 62%->100%) caused by millions of small thumbnail cache files; 'No space left on device' fires while 412GB and 48% used show plenty of byte space. Must name inodes (not disk space) and the tiny-files cache as the driver.

bench2_03.log: root cause = DST fall-back: the 01:30 local cron slot occurred twice on 2026-11-01 (EDT then EST), so job=daily_charges ran twice with the same logical_date (run_id rc-1 and rc-2), double-charging customers. Must connect the duplicate runs at the repeated wall-clock time / DST to the duplicate charges, and suggest idempotency keys or UTC scheduling.

bench2_04.log: root cause = the partner API 'ratehub' changed its contract (X-API-Version header flips 2025-06 -> 2025-11) and began returning quote.terms=null, which our normalize_quote does not handle (TypeError on expiry_ts). No deploy on our side. Must name the upstream version/contract change as the trigger and the missing null-handling as the local weakness.

bench2_05.log: root cause = a hot key (user:celeb_8812) concentrating traffic on shard=7 (~14x skew): only shard 7 shows 400-4000ms latency and pool saturation, shards 0-6 healthy. Must localize to shard 7 + the hot key, and suggest caching/splitting the hot key, not 'database is slow'.

bench2_06.log: root cause = the pod was rescheduled (spot reclaim) from node-a1 to node-b7 where its cpu limit is 500m instead of 4000m -> heavy cgroup CPU throttling (throttled_pct climbs to ~94%) -> inference latency 80ms->6s -> gateway timeouts. Must name the reschedule + cpu limit/throttling chain, not 'model got slow'.

bench2_07.log: root cause = client acme-corp started sending ~10-14MB documents (payload_bytes trend jumps ~20x) -> JVM G1 'Humongous Allocation' GC pauses of 0.9-4.2s -> processing slots starve, timeouts. Must connect the payload-size jump from a specific client to the humongous-allocation GC thrash; fix = payload limits/streaming parsing, not 'add memory'.

bench2_08.log: root cause = split brain: a rack-a<->rack-b network partition (34% loss) plus quorum_mode=available lets BOTH kv-a1 (term 41) and kv-b2 (term 42) act as leaders and commit writes -> replication conflicts / diverged versions. Must identify two simultaneous leaders + the unsafe quorum config, not just 'replication errors'.

bench2_09.log: root cause = the SMS provider's monthly quota (plan starter-10k) was already at ~97-100% and hard-exhausted right at the month boundary — QUOTA_EXCEEDED 429s begin at 00:00 Sep 1. Must connect the quota/plan limit and the month rollover timing; fix = raise plan/alerting on quota, not 'provider outage'.

bench2_10.log: root cause = config drift: the feature.new_auth rollout reached api-1 and api-2 but api-3 was unreachable and never retried, so api-3 still rejects v2-signed tokens — all failures concentrate on instance=api-3. Must localize to api-3 + the failed rollout line, and suggest re-applying config / rollout retries.
