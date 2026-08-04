bench_01.log: root cause = 9-16s GC pauses on consumer c-3 only, exceeding session.timeout of 10s -> it gets kicked from the group -> endless group rebalances -> lag grows. Must name c-3 and GC/timeout, not just 'Kafka is broken'.

bench_02.log: root cause = the api.corp.com certificate expired at 10:00 (notAfter matches the error onset exactly). Must connect notAfter with the moment errors start.

bench_03.log: root cause = clock skew on api-2 (ntpd drift 187s, no sync) -> jwt 'iat in future' errors only on api-2. Must localize to api-2 and name clock/NTP desync.

bench_04.log: root cause = CONFIG SET maxmemory 512mb (was 8gb) applied by config-sync -> mass evictions, hit rate 0.97->0.31 -> load shifts to Postgres, latency grows. Must name the maxmemory change.

bench_05.log: root cause = the nightly pg_basebackup (02:00-02:40) saturating db-1's disk (io_util ~100%, read_wait hundreds of ms) -> slow queries strictly within the backup window. Must connect the degradation window with the backup.

bench_06.log: root cause = after the http-client 4->5 upgrade connections are not reused/closed (established and idle_never_closed grow monotonically) -> fd exhaustion (EMFILE). Must name the library upgrade and the connection leak.

bench_07.log: root cause = after the cutover, volume to provider paylink grew x2.1 -> paylink responds 429 (Retry-After), retries amplify. Must connect the cutover with the 429/rate limit, not blame the network.

bench_08.log: root cause = the log sink switched to NFS in sync mode; the NFS server stalls (op WRITE timeout) -> all 40 threads stuck in log_write -> thread pool exhausted, requests time out. Must name NFS/synchronous logging, not just 'the service is slow'.

bench_09.log: root cause = canary build=9e1c77: NPE in PriceFormatter with discount=null, all 500s only on the canary (10% of traffic), the main build is healthy. Must localize to build=9e1c77 and suggest rolling back the canary.

bench_10.log: root cause = health-check flapping of instance i-04 (tcp check timeout 1s < app warmup 3s) -> envoy rebuilds config every ~2s -> envoy RSS grows (180->900MB) + bursts of 503 no_healthy_upstream. The ideal answer names the flapping health check as the first cause and envoy memory as a consequence.
