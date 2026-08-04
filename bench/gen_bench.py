#!/usr/bin/env python3
"""Слепой бенчмарк: 10 новых типов отказов, которых loglens v2 не видел.
Код loglens заморожен ДО генерации этих сценариев."""
import random
from datetime import datetime, timedelta

random.seed(2026)
TRUTH = []


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0,999):03d}Z"


def write(name, lines, truth):
    with open(name, "w") as f:
        f.write("\n".join(lines) + "\n")
    TRUTH.append(f"{name}: {truth}")


def noise(dt, svc="api", n=1):
    out = []
    for _ in range(n):
        out.append(f"{ts(dt)} INFO  {svc} handled /v1/{random.choice(['users','orders','items'])} status=200 latency={random.randint(20,90)}ms")
    return out


# 1. Kafka rebalance storm: у консьюмера c-3 длинные GC-паузы -> вылетает из группы -> вечный ребаланс, лаг растёт
def s1():
    L, t = [], datetime(2026, 8, 4, 11, 0)
    for i in range(900):
        t += timedelta(seconds=random.uniform(0.5, 2))
        r = random.random()
        if r < 0.4:
            L += noise(t, "consumer")
        elif r < 0.55:
            c = random.choice(["c-1", "c-2", "c-3"])
            pause = random.randint(9000, 16000) if c == "c-3" else random.randint(20, 180)
            L.append(f"{ts(t)} INFO  consumer id={c} gc pause={pause}ms")
        elif r < 0.75:
            L.append(f"{ts(t)} WARN  kafka group orders-cg rebalance triggered: member c-3 session timed out (session.timeout.ms=10000)")
            L.append(f"{ts(t)} INFO  kafka group orders-cg rebalance complete generation={i}")
        else:
            L.append(f"{ts(t)} WARN  kafka consumer lag topic=orders partition={random.randint(0,11)} lag={2000 + i*40}")
    write("bench_01.log", L, "root cause = GC-паузы 9-16s только у консьюмера c-3 превышают session.timeout 10s -> его выкидывает -> бесконечные ребалансы группы -> лаг растёт. Должен назвать c-3 и GC/таймаут, а не 'Kafka сломался'.")


# 2. Истёкший TLS-сертификат: ошибки начинаются ровно в момент истечения
def s2():
    L, t = [], datetime(2026, 8, 4, 9, 30)
    L.append(f"{ts(t)} INFO  gateway loaded cert for api.corp.com serial=4f:2a notAfter=2026-08-04T10:00:00Z")
    while t < datetime(2026, 8, 4, 10, 0):
        t += timedelta(seconds=random.uniform(1, 3)); L += noise(t, "gateway")
    while t < datetime(2026, 8, 4, 10, 25):
        t += timedelta(seconds=random.uniform(0.3, 1))
        if random.random() < 0.7:
            L.append(f"{ts(t)} ERROR gateway TLS handshake failed client={random.randint(1,99)}: x509: certificate has expired or is not yet valid")
        else:
            L.append(f"{ts(t)} WARN  upstream-monitor api.corp.com probe failed: ssl verification error")
    write("bench_02.log", L, "root cause = сертификат api.corp.com истёк в 10:00 (notAfter совпадает с началом ошибок). Должен связать notAfter и момент начала ошибок.")


# 3. Clock skew: на api-2 уехали часы, токены 'used before issued' только там
def s3():
    L, t = [], datetime(2026, 8, 4, 13, 0)
    L.append(f"{ts(t)} WARN  ntpd host=api-2 no server suitable for synchronization found, drift 187s")
    for i in range(700):
        t += timedelta(seconds=random.uniform(0.4, 1.5))
        h = random.choice(["api-1", "api-2", "api-3"])
        if h == "api-2" and random.random() < 0.6:
            L.append(f"{ts(t)} ERROR auth host={h} jwt validation failed: token used before issued (iat in future)")
        else:
            L.append(f"{ts(t)} INFO  auth host={h} token issued ok uid=<{random.randint(1,9)}>")
    write("bench_03.log", L, "root cause = clock skew на api-2 (ntpd drift 187s, нет синхронизации) -> jwt 'iat in future' только на api-2. Должен локализовать до api-2 и назвать рассинхрон часов/NTP.")


# 4. Redis maxmemory урезали конфигом: hit rate падает, БД захлёбывается
def s4():
    L, t = [], datetime(2026, 8, 4, 15, 40)
    hit = 0.97
    for i in range(800):
        t += timedelta(seconds=random.uniform(0.5, 2))
        if i == 120:
            L.append(f"{ts(t)} INFO  redis CONFIG SET maxmemory 512mb (was 8gb) applied by config-sync job")
        r = random.random()
        if r < 0.35:
            L += noise(t, "catalog")
        elif r < 0.55:
            if i > 120:
                hit = max(0.31, hit - 0.004)
            L.append(f"{ts(t)} INFO  redis stats hit_rate={hit:.2f} evicted_keys={0 if i<120 else random.randint(3000,90000)} used_memory={'7.4gb' if i<120 else '512mb'}")
        elif r < 0.8:
            lat = random.randint(15, 40) if i < 120 else random.randint(90, 1400)
            L.append(f"{ts(t)} INFO  catalog db query products_by_id latency={lat}ms rows=<n>")
        else:
            if i > 300:
                L.append(f"{ts(t)} WARN  postgres connections active={random.randint(140,190)}/200 slow queries={random.randint(5,60)}")
            else:
                L.append(f"{ts(t)} INFO  postgres connections active={random.randint(20,45)}/200")
    write("bench_04.log", L, "root cause = CONFIG SET maxmemory 512mb (было 8gb) от config-sync -> массовые evictions, hit rate 0.97->0.31 -> нагрузка ушла в Postgres, латентность выросла. Должен назвать смену maxmemory.")


# 5. Ночной бэкап сатурирует диск: запросы тормозят строго в окно бэкапа
def s5():
    L, t = [], datetime(2026, 8, 4, 1, 30)
    for i in range(900):
        t += timedelta(seconds=random.uniform(1, 4))
        in_backup = datetime(2026, 8, 4, 2, 0) <= t <= datetime(2026, 8, 4, 2, 40)
        if i % 200 == 0 and in_backup:
            L.append(f"{ts(t)} INFO  cron pg_basebackup started target=/backup/nightly io_class=best-effort")
        r = random.random()
        if r < 0.5:
            lat = random.randint(400, 3000) if in_backup else random.randint(25, 80)
            L.append(f"{ts(t)} INFO  orders db query latency={lat}ms")
        elif r < 0.7:
            util = random.randint(97, 100) if in_backup else random.randint(10, 40)
            L.append(f"{ts(t)} INFO  node-exporter db-1 disk_io_util={util}% read_wait={random.randint(200,900) if in_backup else random.randint(1,9)}ms")
        elif r < 0.8 and in_backup:
            L.append(f"{ts(t)} WARN  orders query exceeded slow-log threshold: SELECT ... FOR UPDATE waited {random.randint(1000,6000)}ms")
        else:
            L += noise(t, "orders")
    write("bench_05.log", L, "root cause = ночной pg_basebackup (02:00-02:40) сатурирует диск db-1 (io_util ~100%, read_wait сотни ms) -> медленные запросы строго в окне бэкапа. Должен связать окно деградации с бэкапом.")


# 6. Утечка коннекшенов после апгрейда библиотеки
def s6():
    L, t = [], datetime(2026, 8, 4, 16, 0)
    conns = 12
    L.append(f"{ts(t)} INFO  inventory-svc dependency upgraded: http-client 4.2.0 -> 5.0.0 (changelog: connection reuse rewritten)")
    for i in range(850):
        t += timedelta(seconds=random.uniform(0.5, 2))
        conns += random.uniform(0.15, 0.5)
        r = random.random()
        if r < 0.5:
            L += noise(t, "inventory-svc")
        elif r < 0.7:
            L.append(f"{ts(t)} INFO  inventory-svc conn-pool established={int(conns)} idle_never_closed={int(conns*0.8)}")
        elif conns > 240 and r < 0.9:
            L.append(f"{ts(t)} ERROR inventory-svc connect to warehouse-api failed: too many open files (EMFILE)")
        else:
            L.append(f"{ts(t)} INFO  inventory-svc fd_count={int(1000 + conns*4)}")
    write("bench_06.log", L, "root cause = после апгрейда http-client 4->5 соединения не переиспользуются/не закрываются (established и idle_never_closed растут монотонно) -> исчерпание fd (EMFILE). Должен назвать апгрейд библиотеки и утечку соединений.")


# 7. Третья сторона включила rate limit после переключения трафика
def s7():
    L, t = [], datetime(2026, 8, 4, 12, 0)
    L.append(f"{ts(t)} INFO  traffic cutover complete: region eu-1 now routes through provider=paylink (volume x2.1)")
    for i in range(800):
        t += timedelta(seconds=random.uniform(0.3, 1.2))
        r = random.random()
        if r < 0.45:
            L += noise(t, "checkout")
        elif r < 0.75:
            code = 429 if random.random() < (0.05 + min(i, 400) / 700) else 200
            L.append(f"{ts(t)} {'ERROR' if code==429 else 'INFO '} checkout paylink POST /charge status={code}{' Retry-After=30' if code==429 else ''} latency={random.randint(80,300)}ms")
        else:
            L.append(f"{ts(t)} WARN  checkout retry scheduled attempt={random.randint(1,6)} reason=rate_limited provider=paylink")
    write("bench_07.log", L, "root cause = после cutover объём на провайдера paylink вырос x2.1 -> paylink отвечает 429 (Retry-After), ретраи усугубляют. Должен связать cutover c 429/rate limit, а не винить сеть.")


# 8. Синхронное логирование на затормозивший NFS душит тред-пул
def s8():
    L, t = [], datetime(2026, 8, 4, 17, 30)
    L.append(f"{ts(t)} INFO  reports-svc log sink changed: /var/log/local -> nfs://logstore/reports (sync mode)")
    for i in range(750):
        t += timedelta(seconds=random.uniform(0.4, 1.6))
        nfs_slow = i > 200
        r = random.random()
        if r < 0.4:
            lat = random.randint(2000, 9000) if nfs_slow else random.randint(30, 90)
            L.append(f"{ts(t)} INFO  reports-svc handled /report status=200 latency={lat}ms")
        elif r < 0.6:
            L.append(f"{ts(t)} INFO  reports-svc threadpool active={40 if nfs_slow else random.randint(3,10)}/40 queued={random.randint(200,900) if nfs_slow else 0}")
        elif r < 0.75 and nfs_slow:
            L.append(f"{ts(t)} WARN  nfs client logstore: server not responding, still trying (op WRITE timeout {random.randint(3,30)}s)")
        elif r < 0.85 and nfs_slow:
            L.append(f"{ts(t)} WARN  reports-svc request timed out waiting for worker thread (all busy in log_write)")
        else:
            L += noise(t, "reports-svc")
    write("bench_08.log", L, "root cause = лог-синк переключён на NFS в sync-режиме; NFS-сервер тормозит (op WRITE timeout) -> все 40 тредов застревают в log_write -> тред-пул исчерпан, запросы таймаутят. Должен назвать NFS/синхронное логирование, а не 'сервис медленный'.")


# 9. Плохая канарейка: 500-е только у build=9e1c77
def s9():
    L, t = [], datetime(2026, 8, 4, 19, 15)
    L.append(f"{ts(t)} INFO  canary rollout: 10% traffic -> build=9e1c77 (main build=5b0a12)")
    for i in range(900):
        t += timedelta(seconds=random.uniform(0.2, 0.9))
        canary = random.random() < 0.1
        b = "9e1c77" if canary else "5b0a12"
        if canary and random.random() < 0.55:
            L.append(f"{ts(t)} ERROR web build={b} unhandled NullPointerException in PriceFormatter.apply(discount=null) status=500")
        else:
            L.append(f"{ts(t)} INFO  web build={b} handled /product status=200 latency={random.randint(25,95)}ms")
    write("bench_09.log", L, "root cause = канареечный build=9e1c77: NPE в PriceFormatter при discount=null, все 500-е только на канарейке (10% трафика), main build здоров. Должен локализовать до build=9e1c77 и предложить откат канарейки.")


# 10. Envoy-сайдкар: flapping service discovery -> реконфиг каждые 2s -> рост RSS
def s10():
    L, t = [], datetime(2026, 8, 4, 20, 40)
    rss = 180
    for i in range(850):
        t += timedelta(seconds=random.uniform(0.5, 1.8))
        r = random.random()
        if r < 0.3:
            L.append(f"{ts(t)} INFO  envoy cds: update rejected then accepted, cluster search-backend endpoints 3 -> 0 -> 3 (flap #{i})")
        elif r < 0.5:
            rss += random.uniform(0.4, 1.2)
            L.append(f"{ts(t)} INFO  envoy memory rss={int(rss)}MB heap={int(rss*0.7)}MB config_reloads_total={i*2}")
        elif r < 0.65:
            L.append(f"{ts(t)} WARN  service-discovery search-backend health flapping: instance i-04 alternating healthy/unhealthy every ~2s (tcp check timeout 1s, app warmup 3s)")
        elif r < 0.8 and rss > 700:
            L.append(f"{ts(t)} WARN  envoy upstream search-backend 503 no_healthy_upstream burst={random.randint(2,30)}")
        else:
            L += noise(t, "search")
    write("bench_10.log", L, "root cause = health-check flapping инстанса i-04 (tcp timeout 1s < warmup 3s) -> envoy пересобирает конфиг каждые ~2s -> RSS envoy растёт (180->900MB) + всплески 503 no_healthy_upstream. Идеальный ответ называет flapping health-check как первопричину, envoy-память как следствие.")


for f in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10):
    f()
with open("bench_truth.md", "w") as fh:
    fh.write("\n\n".join(TRUTH) + "\n")
print("bench_01..10.log written")
