Scenario 1: root cause = включённый в рантайме фича-флаг result_cache_debug, который хранит полные копии ответов → кеш неограниченно растёт (см. cache: entries/bytes), heap растёт, GC-паузы удлиняются, латентность деградирует. OOM ещё не случился. Правильный ответ должен указать на флаг/кеш, а не просто 'утечка памяти'.

Scenario 2: root cause = дедлок из-за несогласованного порядка взятия advisory-локов после миграции 0142: job=charge берёт invoice→ждёт ledger, job=reconcile берёт ledger→ждёт invoice. Ответ должен назвать взаимную блокировку/порядок локов, миграцию как триггер.

Scenario 3: root cause = после ротации нод node-7 получил legacy nameserver 10.0.0.53 (выведенный DNS): все ошибки резолва только у pod-ов на node-7, остальные ноды здоровы. Ответ должен локализовать проблему до node-7 + указать legacy DNS из строки про ротацию.

Scenario 4: root cause = заполнившийся диск на db-1 (/var/lib/postgresql, node-exporter показывает рост к 99.8%) → медленные checkpoint/fsync → зависшие коммиты → 'No space left on device'. Громкие ошибки metrics-exporter 404 и TLS handshake — шум/красная селёдка, их надо явно отвергнуть.
