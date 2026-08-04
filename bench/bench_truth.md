bench_01.log: root cause = GC-паузы 9-16s только у консьюмера c-3 превышают session.timeout 10s -> его выкидывает -> бесконечные ребалансы группы -> лаг растёт. Должен назвать c-3 и GC/таймаут, а не 'Kafka сломался'.

bench_02.log: root cause = сертификат api.corp.com истёк в 10:00 (notAfter совпадает с началом ошибок). Должен связать notAfter и момент начала ошибок.

bench_03.log: root cause = clock skew на api-2 (ntpd drift 187s, нет синхронизации) -> jwt 'iat in future' только на api-2. Должен локализовать до api-2 и назвать рассинхрон часов/NTP.

bench_04.log: root cause = CONFIG SET maxmemory 512mb (было 8gb) от config-sync -> массовые evictions, hit rate 0.97->0.31 -> нагрузка ушла в Postgres, латентность выросла. Должен назвать смену maxmemory.

bench_05.log: root cause = ночной pg_basebackup (02:00-02:40) сатурирует диск db-1 (io_util ~100%, read_wait сотни ms) -> медленные запросы строго в окне бэкапа. Должен связать окно деградации с бэкапом.

bench_06.log: root cause = после апгрейда http-client 4->5 соединения не переиспользуются/не закрываются (established и idle_never_closed растут монотонно) -> исчерпание fd (EMFILE). Должен назвать апгрейд библиотеки и утечку соединений.

bench_07.log: root cause = после cutover объём на провайдера paylink вырос x2.1 -> paylink отвечает 429 (Retry-After), ретраи усугубляют. Должен связать cutover c 429/rate limit, а не винить сеть.

bench_08.log: root cause = лог-синк переключён на NFS в sync-режиме; NFS-сервер тормозит (op WRITE timeout) -> все 40 тредов застревают в log_write -> тред-пул исчерпан, запросы таймаутят. Должен назвать NFS/синхронное логирование, а не 'сервис медленный'.

bench_09.log: root cause = канареечный build=9e1c77: NPE в PriceFormatter при discount=null, все 500-е только на канарейке (10% трафика), main build здоров. Должен локализовать до build=9e1c77 и предложить откат канарейки.

bench_10.log: root cause = health-check flapping инстанса i-04 (tcp timeout 1s < warmup 3s) -> envoy пересобирает конфиг каждые ~2s -> RSS envoy растёт (180->900MB) + всплески 503 no_healthy_upstream. Идеальный ответ называет flapping health-check как первопричину, envoy-память как следствие.
