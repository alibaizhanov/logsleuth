## Symptom  
Redis hit rate dropped to 0.5, evicted keys surged, and PostgreSQL slow queries spiked, causing increased latency in catalog database queries.  

## Timeline  
- **2026-08-04T15:42:40.982Z**: Redis `maxmemory` reduced to 512MB via config-sync job.  
- **2026-08-04T15:46:34.646Z**: PostgreSQL connections active=152/200, slow queries=50.  
- **2026-08-04T15:56:46.717Z**: PostgreSQL connections active=172/200, slow queries=37.  
- **2026-08-04T15:56:33.833Z**: Redis hit_rate=0.39, evicted_keys=68593 (peak).  

## Root cause hypothesis  
**Redis memory configuration change** (confidence: high); evidence:  
- "redis CONFIG SET maxmemory 512mb (was 8gb)" (line 121)  
- "redis stats hit_rate=0.39 evicted_keys=68593" (line 395)  
- "hit_rate DROPPED 1.0 -> 0.5" and "evicted_keys GREW 15531.9 -> 52811.0" (numeric trends).  

Redis memory was reduced to 512MB, triggering key evictions and cache misses. This forced the catalog service to query PostgreSQL more frequently, overwhelming its connection pool and causing slow queries.  

## Ruled out  
- **PostgreSQL connection limits**: Active connections (152/200) were within configured limits; the issue was not connection exhaustion but query performance.  
- **Baseline noise**: "connections active=<n>/<n>" patterns were present before the incident and not correlated with the spike in slow queries.  

## Suggested next steps  
1. **Audit Redis memory configuration**: Verify if the 512MB limit was intentional and assess if it caused unnecessary evictions.  
2. **Monitor cache efficiency**: Track Redis hit rate and evicted keys post-configuration to validate impact.  
3. **Optimize PostgreSQL queries**: Analyze slow queries (e.g., `products_by_id`) and index missing columns.  
4. **Adjust connection pool limits**: Temporarily increase PostgreSQL connection limits to prevent future contention.  
5. **Implement cache warming**: Preload critical data into Redis to mitigate evictions during peak loads.
