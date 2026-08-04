#!/usr/bin/env python3
"""Четыре коварных сценария для бенчмарка logsleuth.

Каждый пишет scenario_N.log и печатает GROUND TRUTH (правильный ответ)
в scenarios_truth.md — для честной оценки попаданий.
"""
import random
from datetime import datetime, timedelta

random.seed(7)
TRUTH = []


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0,999):03d}Z"


# ---------- Сценарий 1: утечка памяти БЕЗ OOM-строки ----------
# Иголка: включённый debug-кеш после включения фича-флага, heap растёт,
# GC-паузы удлиняются, латентность деградирует. Никакого OOM/FATAL.
def scenario1():
    lines = []
    t = datetime(2026, 8, 4, 9, 0)
    heap = 900
    gc_pause = 12
    lines.append(f"{ts(t)} INFO  search-api feature flag 'result_cache_debug' enabled via runtime config by ops@corp (keeps full response copies for diffing)")
    for step in range(1400):
        t += timedelta(seconds=random.uniform(1, 4))
        heap += random.uniform(0.8, 2.4)
        if step % 40 == 0:
            gc_pause = int(gc_pause * 1.13)
        r = random.random()
        if r < 0.6:
            lat = int(35 + heap / 18 + random.randint(0, 30))
            lines.append(f"{ts(t)} INFO  search-api handled /search status=200 latency={lat}ms")
        elif r < 0.8:
            lines.append(f"{ts(t)} INFO  search-api gc: pause={gc_pause}ms heap_used={int(heap)}MB heap_max=4096MB survivors={random.randint(100,900)}k")
        elif r < 0.9:
            lines.append(f"{ts(t)} INFO  search-api cache: entries={int(heap*310)} bytes={int(heap*0.71)}MB hit_rate=0.{random.randint(88,97)}")
        else:
            if gc_pause > 400:
                lines.append(f"{ts(t)} WARN  search-api request exceeded SLA: /search latency={random.randint(1200, 4000)}ms (SLA 800ms)")
            else:
                lines.append(f"{ts(t)} INFO  search-api healthcheck ok")
    with open("scenario_1.log", "w") as f:
        f.write("\n".join(lines) + "\n")
    TRUTH.append("Scenario 1: root cause = включённый в рантайме фича-флаг result_cache_debug, который хранит полные копии ответов → кеш неограниченно растёт (см. cache: entries/bytes), heap растёт, GC-паузы удлиняются, латентность деградирует. OOM ещё не случился. Правильный ответ должен указать на флаг/кеш, а не просто 'утечка памяти'.")


# ---------- Сценарий 2: дедлок без слова deadlock ----------
# Иголка: после миграции добавлен второй advisory lock; воркеры берут
# lock A и B в разном порядке, зависают попарно. В логах — только
# 'still waiting for lock' и рост in-flight, слово deadlock не встречается.
def scenario2():
    lines = []
    t = datetime(2026, 8, 4, 14, 20)
    lines.append(f"{ts(t)} INFO  billing-worker applied migration 0142_add_ledger_lock (introduces advisory lock 'ledger' in addition to 'invoice')")
    for i in range(600):
        t += timedelta(seconds=random.uniform(0.5, 2))
        lines.append(f"{ts(t)} INFO  billing-worker job=charge id=<{random.randint(1000,9999)}> acquired lock 'invoice' waiting lock 'ledger'")
        if random.random() < 0.5:
            lines.append(f"{ts(t)} INFO  billing-worker job=reconcile id=<{random.randint(1000,9999)}> acquired lock 'ledger' waiting lock 'invoice'")
        if i % 25 == 0:
            lines.append(f"{ts(t)} WARN  billing-worker still waiting for lock 'ledger' elapsed={random.randint(30,600)}s job=charge")
            lines.append(f"{ts(t)} WARN  billing-worker still waiting for lock 'invoice' elapsed={random.randint(30,600)}s job=reconcile")
        if i % 50 == 0:
            lines.append(f"{ts(t)} WARN  billing-worker in-flight jobs={200 + i} completed_last_min={max(0, 40 - i//12)}")
    lines.append(f"{ts(t)} ERROR billing-worker queue depth 18400 exceeds limit, new jobs rejected")
    with open("scenario_2.log", "w") as f:
        f.write("\n".join(lines) + "\n")
    TRUTH.append("Scenario 2: root cause = дедлок из-за несогласованного порядка взятия advisory-локов после миграции 0142: job=charge берёт invoice→ждёт ledger, job=reconcile берёт ledger→ждёт invoice. Ответ должен назвать взаимную блокировку/порядок локов, миграцию как триггер.")


# ---------- Сценарий 3: мигающий DNS ----------
# Иголка: после ротации нод кластера у одной из трёх нод резолвер смотрит
# на выведенный из эксплуатации DNS 10.0.0.53; ошибки только с pod-ов ноды node-7.
def scenario3():
    lines = []
    t = datetime(2026, 8, 4, 18, 5)
    lines.append(f"{ts(t)} INFO  cluster node rotation complete: node-7 joined (image v1.31.2), node-3 drained. kubelet dns config: nameserver 10.0.0.53 (legacy)")
    pods = {"node-7": ["api-5f", "api-9c"], "node-2": ["api-1a", "api-3d"], "node-5": ["api-7b"]}
    for i in range(1800):
        t += timedelta(seconds=random.uniform(0.3, 1.5))
        node = random.choice(list(pods))
        pod = random.choice(pods[node])
        if node == "node-7" and random.random() < 0.45:
            kind = random.choice([
                "getaddrinfo EAI_AGAIN payments.internal.corp",
                "dial tcp: lookup payments.internal.corp on 10.0.0.53:53: read udp timeout",
                "lookup auth.internal.corp on 10.0.0.53:53: no such host (intermittent)",
            ])
            lines.append(f"{ts(t)} ERROR api pod={pod} node={node} upstream call failed: {kind} retry={random.randint(0,3)}")
        else:
            lines.append(f"{ts(t)} INFO  api pod={pod} node={node} handled /v1/pay status=200 latency={random.randint(30,120)}ms")
    with open("scenario_3.log", "w") as f:
        f.write("\n".join(lines) + "\n")
    TRUTH.append("Scenario 3: root cause = после ротации нод node-7 получил legacy nameserver 10.0.0.53 (выведенный DNS): все ошибки резолва только у pod-ов на node-7, остальные ноды здоровы. Ответ должен локализовать проблему до node-7 + указать legacy DNS из строки про ротацию.")


# ---------- Сценарий 4: красная селёдка ----------
# Шум: тысячи громких, но безобидных ошибок 'metrics-exporter 404' и
# 'TLS handshake error from scanner'. Реальная причина: диск заполнен на
# db-нode → fsync медленный → коммиты зависают. Тихие строки про disk.
def scenario4():
    lines = []
    t = datetime(2026, 8, 4, 22, 40)
    disk = 91.0
    for i in range(2200):
        t += timedelta(seconds=random.uniform(0.2, 1.2))
        r = random.random()
        if r < 0.30:
            lines.append(f"{ts(t)} ERROR metrics-exporter GET /metrics/v1 404 not found (deprecated path, dashboard misconfig)")
        elif r < 0.5:
            lines.append(f"{ts(t)} ERROR ingress TLS handshake error from 185.220.{random.randint(0,255)}.{random.randint(1,254)}: EOF (external scanner)")
        elif r < 0.75:
            lines.append(f"{ts(t)} INFO  orders-api handled /checkout status=200 latency={random.randint(40, 40 + int(disk-88)*60)}ms")
        elif r < 0.85:
            disk = min(99.8, disk + 0.004)
            if i % 120 == 0:
                lines.append(f"{ts(t)} INFO  node-exporter db-1 disk /var/lib/postgresql usage={disk:.1f}% inodes=61%")
        elif r < 0.95:
            if disk > 97:
                lines.append(f"{ts(t)} WARN  postgres db-1 checkpoint took {random.randint(4000, 30000)}ms (expected <1000ms), fsync slow")
                if random.random() < 0.4:
                    lines.append(f"{ts(t)} WARN  orders-api commit latency {random.randint(2000,9000)}ms txid=<{random.randint(10**6,10**7)}>")
            else:
                lines.append(f"{ts(t)} INFO  postgres db-1 checkpoint complete in {random.randint(300,900)}ms")
        else:
            lines.append(f"{ts(t)} INFO  orders-api healthcheck ok")
    lines.append(f"{ts(t)} ERROR postgres db-1 could not extend file \"base/16384/2619\": No space left on device")
    lines.append(f"{ts(t)} ERROR orders-api transaction aborted: server closed the connection unexpectedly")
    with open("scenario_4.log", "w") as f:
        f.write("\n".join(lines) + "\n")
    TRUTH.append("Scenario 4: root cause = заполнившийся диск на db-1 (/var/lib/postgresql, node-exporter показывает рост к 99.8%) → медленные checkpoint/fsync → зависшие коммиты → 'No space left on device'. Громкие ошибки metrics-exporter 404 и TLS handshake — шум/красная селёдка, их надо явно отвергнуть.")


scenario1(); scenario2(); scenario3(); scenario4()
with open("scenarios_truth.md", "w") as f:
    f.write("\n\n".join(TRUTH) + "\n")
print("done: scenario_1..4.log + scenarios_truth.md")
