#!/usr/bin/env python3
"""Second blind benchmark: 10 MORE failure types, none seen by logsleuth v3.
Code was frozen before these were written. Truth in bench2_truth.md."""
import random
from datetime import datetime, timedelta

random.seed(31337)
TRUTH = []


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0,999):03d}Z"


def write(name, lines, truth):
    with open(name, "w") as f:
        f.write("\n".join(lines) + "\n")
    TRUTH.append(f"{name}: {truth}")


def ok(dt, svc, extra=""):
    return f"{ts(dt)} INFO  {svc} handled request status=200 latency={random.randint(20,90)}ms{extra}"


# 1. Poison-pill message: consumer crashes on the same offset forever
def s1():
    L, t = [], datetime(2026, 8, 5, 8, 0)
    for i in range(700):
        t += timedelta(seconds=random.uniform(0.5, 2))
        r = random.random()
        if r < 0.35:
            L.append(ok(t, "ingest-consumer"))
        elif r < 0.6:
            L.append(f"{ts(t)} INFO  ingest-consumer polled topic=events partition=3 offset={81244 + i} n=25")
        elif r < 0.8:
            L.append(f"{ts(t)} ERROR ingest-consumer failed to decode message topic=events partition=7 offset=90412: protobuf parse error: truncated varint")
            L.append(f"{ts(t)} FATAL ingest-consumer worker crashed, restarting")
            L.append(f"{ts(t)} INFO  ingest-consumer started, resuming topic=events partition=7 offset=90412")
        else:
            L.append(f"{ts(t)} WARN  ingest-consumer partition=7 consumer lag={4000 + i*25} (not advancing)")
    write("bench2_01.log", L, "root cause = a poison-pill message at partition=7 offset=90412 (protobuf truncated varint): the consumer crashes on it, restarts, resumes at the SAME offset and crashes again forever; partition 7 lag never advances while other partitions are fine. Must name the specific stuck offset/poison message and suggest skipping/DLQ, not 'consumer is crashing'.")


# 2. Inode exhaustion: 'no space' while disk has free space
def s2():
    L, t = [], datetime(2026, 8, 5, 10, 30)
    for i in range(700):
        t += timedelta(seconds=random.uniform(0.5, 2))
        r = random.random()
        if r < 0.4:
            L.append(ok(t, "thumb-svc"))
        elif r < 0.6:
            inode = min(100, 62 + i * 0.06)
            L.append(f"{ts(t)} INFO  node-exporter worker-3 disk /var free=412GB used=48% inodes_used={inode:.0f}%")
        elif r < 0.75:
            L.append(f"{ts(t)} INFO  thumb-svc generated thumbnail cache_file=/var/cache/thumbs/{random.randint(10**6,10**7)}.tmp")
        elif i > 450:
            L.append(f"{ts(t)} ERROR thumb-svc write failed /var/cache/thumbs/{random.randint(10**6,10**7)}.tmp: OSError 28 No space left on device")
        else:
            L.append(ok(t, "thumb-svc"))
    write("bench2_02.log", L, "root cause = inode exhaustion on worker-3 /var (inodes_used climbs 62%->100%) caused by millions of small thumbnail cache files; 'No space left on device' fires while 412GB and 48% used show plenty of byte space. Must name inodes (not disk space) and the tiny-files cache as the driver.")


# 3. DST fall-back: cron job runs twice, double charges
def s3():
    L, t = [], datetime(2026, 11, 1, 0, 30)
    L.append(f"{ts(t)} INFO  billing-cron scheduler tz=America/New_York next_run=01:30 local")
    for run in range(2):
        base = datetime(2026, 11, 1, 1, 30) + timedelta(hours=run)  # 01:30 EDT and 01:30 EST
        L.append(f"{ts(base)} INFO  billing-cron job=daily_charges started logical_date=2026-11-01 run_id=rc-{run+1}")
        for i in range(120):
            base += timedelta(seconds=random.uniform(0.2, 0.8))
            L.append(f"{ts(base)} INFO  billing-cron charged account=<{random.randint(100,999)}> amount_cents={random.randint(500,9000)} logical_date=2026-11-01")
        L.append(f"{ts(base)} INFO  billing-cron job=daily_charges finished logical_date=2026-11-01 charged=120")
    t = datetime(2026, 11, 1, 3, 0)
    for i in range(150):
        t += timedelta(seconds=random.uniform(0.5, 2))
        if random.random() < 0.6:
            L.append(f"{ts(t)} ERROR support-api customer complaint: duplicate charge account=<{random.randint(100,999)}> logical_date=2026-11-01")
        else:
            L.append(ok(t, "support-api"))
    write("bench2_03.log", L, "root cause = DST fall-back: the 01:30 local cron slot occurred twice on 2026-11-01 (EDT then EST), so job=daily_charges ran twice with the same logical_date (run_id rc-1 and rc-2), double-charging customers. Must connect the duplicate runs at the repeated wall-clock time / DST to the duplicate charges, and suggest idempotency keys or UTC scheduling.")


# 4. Upstream contract change: partner API starts returning null field
def s4():
    L, t = [], datetime(2026, 8, 5, 14, 0)
    for i in range(800):
        t += timedelta(seconds=random.uniform(0.3, 1.2))
        r = random.random()
        broke = i > 260
        if r < 0.4:
            L.append(ok(t, "quotes-api"))
        elif r < 0.55 and broke and i < 320:
            if i == 261:
                L.append(f"{ts(t)} INFO  quotes-api partner ratehub responded with header X-API-Version: 2025-11 (was 2025-06)")
        elif r < 0.75 and broke:
            L.append(f"{ts(t)} ERROR quotes-api TypeError: cannot read field 'expiry_ts' of null in normalize_quote (partner=ratehub payload field quote.terms=null)")
        elif r < 0.85 and broke:
            L.append(f"{ts(t)} WARN  quotes-api schema validation: unexpected null at quote.terms partner=ratehub")
        else:
            L.append(ok(t, "quotes-api"))
    write("bench2_04.log", L, "root cause = the partner API 'ratehub' changed its contract (X-API-Version header flips 2025-06 -> 2025-11) and began returning quote.terms=null, which our normalize_quote does not handle (TypeError on expiry_ts). No deploy on our side. Must name the upstream version/contract change as the trigger and the missing null-handling as the local weakness.")


# 5. Hot shard: one celebrity key melts shard 7
def s5():
    L, t = [], datetime(2026, 8, 5, 19, 0)
    for i in range(900):
        t += timedelta(seconds=random.uniform(0.2, 0.9))
        shard = random.choices(range(8), weights=[1,1,1,1,1,1,1,14 if i > 200 else 1])[0]
        lat = random.randint(400, 4000) if (shard == 7 and i > 200) else random.randint(10, 60)
        lvl = "WARN " if lat > 1000 else "INFO "
        extra = ""
        if shard == 7 and i > 200 and random.random() < 0.3:
            extra = " key=user:celeb_8812 fanout=hot"
        L.append(f"{ts(t)} {lvl}feed-api query shard={shard} latency={lat}ms{extra}")
        if shard == 7 and i > 400 and random.random() < 0.15:
            L.append(f"{ts(t)} ERROR feed-api shard=7 connection pool saturated, queueing")
    write("bench2_05.log", L, "root cause = a hot key (user:celeb_8812) concentrating traffic on shard=7 (~14x skew): only shard 7 shows 400-4000ms latency and pool saturation, shards 0-6 healthy. Must localize to shard 7 + the hot key, and suggest caching/splitting the hot key, not 'database is slow'.")


# 6. CPU throttling after pod rescheduled to a node with tighter cgroup limits
def s6():
    L, t = [], datetime(2026, 8, 5, 22, 15)
    L.append(f"{ts(t)} INFO  scheduler pod ml-scorer-6b9d evicted from node-a1 (spot reclaim), scheduled to node-b7 (cpu limit 500m, was 4000m)")
    for i in range(750):
        t += timedelta(seconds=random.uniform(0.4, 1.5))
        r = random.random()
        if r < 0.35:
            lat = random.randint(1800, 6000) if i > 30 else random.randint(80, 200)
            L.append(f"{ts(t)} {'WARN ' if lat > 1000 else 'INFO '}ml-scorer inference latency={lat}ms model=ranker-v9")
        elif r < 0.6:
            thr = 40 + min(i, 400) * 2
            L.append(f"{ts(t)} INFO  cadvisor pod=ml-scorer-6b9d cpu_throttled_periods={thr} throttled_pct={min(94, 12 + i//8)}%")
        elif r < 0.75 and i > 100:
            L.append(f"{ts(t)} ERROR gateway upstream timeout calling ml-scorer after 5000ms, using fallback ranking")
        else:
            L.append(ok(t, "gateway"))
    write("bench2_06.log", L, "root cause = the pod was rescheduled (spot reclaim) from node-a1 to node-b7 where its cpu limit is 500m instead of 4000m -> heavy cgroup CPU throttling (throttled_pct climbs to ~94%) -> inference latency 80ms->6s -> gateway timeouts. Must name the reschedule + cpu limit/throttling chain, not 'model got slow'.")


# 7. Humongous allocations: partner doubles payload size, GC thrash
def s7():
    L, t = [], datetime(2026, 8, 6, 9, 40)
    for i in range(800):
        t += timedelta(seconds=random.uniform(0.4, 1.4))
        grew = i > 220
        r = random.random()
        if r < 0.3:
            pb = random.randint(9_000_000, 14_000_000) if grew else random.randint(200_000, 600_000)
            L.append(f"{ts(t)} INFO  doc-ingest received document payload_bytes={pb} client=acme-corp")
        elif r < 0.55:
            pause = random.randint(900, 4200) if grew else random.randint(15, 90)
            L.append(f"{ts(t)} {'WARN ' if pause > 500 else 'INFO '}doc-ingest jvm g1 gc pause={pause}ms cause={'G1 Humongous Allocation' if grew else 'G1 Evacuation Pause'}")
        elif r < 0.7 and grew:
            L.append(f"{ts(t)} WARN  doc-ingest request timed out waiting for processing slot")
        else:
            L.append(ok(t, "doc-ingest"))
    write("bench2_07.log", L, "root cause = client acme-corp started sending ~10-14MB documents (payload_bytes trend jumps ~20x) -> JVM G1 'Humongous Allocation' GC pauses of 0.9-4.2s -> processing slots starve, timeouts. Must connect the payload-size jump from a specific client to the humongous-allocation GC thrash; fix = payload limits/streaming parsing, not 'add memory'.")


# 8. Split brain: network partition yields two leaders
def s8():
    L, t = [], datetime(2026, 8, 6, 13, 5)
    L.append(f"{ts(t)} WARN  cluster-net link degraded between rack-a and rack-b packet_loss=34%")
    for i in range(700):
        t += timedelta(seconds=random.uniform(0.3, 1.2))
        r = random.random()
        if r < 0.25:
            L.append(f"{ts(t)} INFO  kv-store node=kv-a1 role=leader term=41 committing writes")
        elif r < 0.5:
            L.append(f"{ts(t)} INFO  kv-store node=kv-b2 role=leader term=42 committing writes")
        elif r < 0.7:
            L.append(f"{ts(t)} ERROR kv-store replication conflict key=orders/<n> versions diverged (term 41 vs 42), rejecting")
        elif r < 0.85:
            L.append(f"{ts(t)} WARN  kv-store node=kv-a1 cannot reach quorum peers in rack-b, proceeding with local quorum (config: quorum_mode=available)")
        else:
            L.append(ok(t, "kv-api"))
    write("bench2_08.log", L, "root cause = split brain: a rack-a<->rack-b network partition (34% loss) plus quorum_mode=available lets BOTH kv-a1 (term 41) and kv-b2 (term 42) act as leaders and commit writes -> replication conflicts / diverged versions. Must identify two simultaneous leaders + the unsafe quorum config, not just 'replication errors'.")


# 9. Cloud API quota exhausted at billing-month rollover
def s9():
    L, t = [], datetime(2026, 8, 31, 22, 0)
    for i in range(700):
        t += timedelta(seconds=random.uniform(0.5, 2))
        after = t >= datetime(2026, 9, 1, 0, 0)
        r = random.random()
        if r < 0.4:
            L.append(ok(t, "notify-svc"))
        elif r < 0.6:
            used = min(100.0, 97.0 + i * 0.01) if not after else 100.0
            L.append(f"{ts(t)} INFO  notify-svc sms provider quota check: monthly_used={used:.1f}% plan=starter-10k")
        elif after and r < 0.85:
            L.append(f"{ts(t)} ERROR notify-svc sms send failed provider=twilio-like status=429 code=QUOTA_EXCEEDED monthly limit reached on plan starter-10k")
        else:
            L.append(ok(t, "notify-svc"))
    write("bench2_09.log", L, "root cause = the SMS provider's monthly quota (plan starter-10k) was already at ~97-100% and hard-exhausted right at the month boundary — QUOTA_EXCEEDED 429s begin at 00:00 Sep 1. Must connect the quota/plan limit and the month rollover timing; fix = raise plan/alerting on quota, not 'provider outage'.")


# 10. Config drift: one replica missed the config rollout
def s10():
    L, t = [], datetime(2026, 8, 6, 16, 20)
    L.append(f"{ts(t)} INFO  config-rollout feature.new_auth=true applied to api-1, api-2 (api-3 unreachable during rollout, will retry: never)")
    for i in range(800):
        t += timedelta(seconds=random.uniform(0.3, 1.1))
        inst = random.choice(["api-1", "api-2", "api-3"])
        if inst == "api-3" and random.random() < 0.5:
            L.append(f"{ts(t)} ERROR auth-gw instance={inst} token rejected: unknown signature scheme v2 (feature.new_auth=false on this replica)")
        else:
            L.append(f"{ts(t)} INFO  auth-gw instance={inst} token ok scheme=v2 latency={random.randint(10,40)}ms")
    write("bench2_10.log", L, "root cause = config drift: the feature.new_auth rollout reached api-1 and api-2 but api-3 was unreachable and never retried, so api-3 still rejects v2-signed tokens — all failures concentrate on instance=api-3. Must localize to api-3 + the failed rollout line, and suggest re-applying config / rollout retries.")


for f in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10):
    f()
with open("bench2_truth.md", "w") as fh:
    fh.write("\n\n".join(TRUTH) + "\n")
print("bench2_01..10.log written")
