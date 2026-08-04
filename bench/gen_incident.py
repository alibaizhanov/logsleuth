#!/usr/bin/env python3
"""Генератор синтетического инцидента для теста loglens."""
import random
from datetime import datetime, timedelta

random.seed(42)
t = datetime(2026, 8, 3, 2, 10, 0)
lines = []
ROUTES = ["/api/v2/charge", "/api/v2/refund", "/api/v2/status", "/healthz"]
IDS = [f"req-{random.randint(10**8, 10**9)}" for _ in range(50)]


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0,999):03d}Z"


def info(dt, msg):
    lines.append(f"{ts(dt)} INFO  payment-service {msg}")


def err(dt, level, msg):
    lines.append(f"{ts(dt)} {level} payment-service {msg}")


# Фаза 0: нормальная работа, 02:10–02:47
while t < datetime(2026, 8, 3, 2, 47):
    info(t, f"handled {random.choice(ROUTES)} status=200 latency={random.randint(18,90)}ms rid={random.choice(IDS)}")
    if random.random() < 0.03:
        info(t, f"pg pool: in_use={random.randint(4,12)}/50 idle={random.randint(30,44)}")
    t += timedelta(seconds=random.uniform(0.5, 3))

# Деплой в 02:47
info(t, "deployment finished: payment-service v2.14.0 (config: PG_POOL_MAX=10, was 50)  commit=9f3ab21")
t += timedelta(seconds=5)

# Фаза 1: деградация 02:47–02:55 — пул мал, латентность растёт
while t < datetime(2026, 8, 3, 2, 55):
    r = random.random()
    if r < 0.5:
        info(t, f"handled {random.choice(ROUTES)} status=200 latency={random.randint(150,900)}ms rid={random.choice(IDS)}")
    elif r < 0.75:
        err(t, "WARN ", f"pg pool: acquire slow wait={random.randint(200,1800)}ms in_use=10/10 idle=0 waiters={random.randint(1,25)}")
    else:
        err(t, "ERROR", f"pg pool timeout after 2000ms acquiring connection rid={random.choice(IDS)} route={random.choice(ROUTES[:2])}")
    t += timedelta(seconds=random.uniform(0.2, 1.2))

# Фаза 2: каскад 02:55–03:05 — таймауты, ретраи, 5xx, thundering herd
while t < datetime(2026, 8, 3, 3, 5):
    r = random.random()
    if r < 0.35:
        err(t, "ERROR", f"pg pool timeout after 2000ms acquiring connection rid={random.choice(IDS)} route={random.choice(ROUTES[:2])}")
    elif r < 0.55:
        err(t, "ERROR", f"upstream gateway returned 502 for {random.choice(ROUTES[:2])} rid={random.choice(IDS)} retry={random.randint(1,5)}")
    elif r < 0.7:
        err(t, "WARN ", f"retry storm detected: {random.randint(300,1200)} pending retries in queue, backoff disabled by config RETRY_BACKOFF=none")
    elif r < 0.8:
        err(t, "ERROR", "psycopg2.OperationalError: FATAL: sorry, too many clients already")
        lines.append("Traceback (most recent call last):")
        lines.append('  File "/app/db/pool.py", line 88, in acquire')
        lines.append("    conn = await self._pool.acquire(timeout=2.0)")
        lines.append("asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already")
    else:
        info(t, f"handled /healthz status=200 latency={random.randint(1,9)}ms")
    t += timedelta(seconds=random.uniform(0.1, 0.8))

# Фаза 3: OOM 03:05–03:09 — очередь ретраев съела память
while t < datetime(2026, 8, 3, 3, 9):
    r = random.random()
    if r < 0.4:
        err(t, "WARN ", f"memory usage {random.randint(88,97)}% rss={random.randint(3600,3980)}MB limit=4096MB retry_queue_len={random.randint(4000,18000)}")
    else:
        err(t, "ERROR", f"request queue full, shedding load rid={random.choice(IDS)}")
    t += timedelta(seconds=random.uniform(0.3, 1.5))

err(t, "FATAL", "container killed: OOMKilled (exit 137), rss=4096MB limit=4096MB")
t += timedelta(seconds=20)
err(t, "ERROR", "kubelet: Back-off restarting failed container payment-service pod=payment-service-7d9f8b-x2k4j")

with open("incident.log", "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"written incident.log: {len(lines)} lines")
