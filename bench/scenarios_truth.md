Scenario 1: root cause = the runtime feature flag result_cache_debug, which keeps full response copies -> the cache grows without bound (see cache: entries/bytes), heap grows, GC pauses lengthen, latency degrades. No OOM yet. A correct answer must point at the flag/cache, not just say 'memory leak'.

Scenario 2: root cause = a deadlock from inconsistent advisory-lock ordering after migration 0142: job=charge takes invoice then waits for ledger, job=reconcile takes ledger then waits for invoice. Must name the mutual blocking / lock ordering, with the migration as the trigger.

Scenario 3: root cause = after the node rotation, node-7 got the legacy nameserver 10.0.0.53 (decommissioned DNS): all resolution errors come from pods on node-7 only, other nodes are healthy. Must localize to node-7 and cite the legacy DNS from the rotation line.

Scenario 4: root cause = the disk filling up on db-1 (/var/lib/postgresql, node-exporter shows growth to 99.8%) -> slow checkpoint/fsync -> stuck commits -> 'No space left on device'. The loud metrics-exporter 404 and TLS handshake errors are noise/red herrings and must be explicitly ruled out.
