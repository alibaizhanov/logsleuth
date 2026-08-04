## Symptom  
High latency spikes in `feed-api` queries to shard 7, culminating in connection pool saturation errors.  

## Timeline  
- **19:01:55** First latency warning for shard 7 (1241ms).  
- **19:08:12** Connection pool saturation error for shard 7 ("queueing").  
- **19:08:14** Final latency spike (3145ms) for shard 7.  

## Root cause hypothesis  
**feed-api shard 7 database connection pool exhaustion**; confidence: **high**.  
Evidence:  
- "ERROR feed-api shard=7 connection pool saturated, queueing" (direct indicator).  
- Latency for shard 7 grew from 1241ms to 3860ms (x3x) over 6.5 minutes.  
- All error-like logs (457/953) are tied to shard=7.  

## Ruled out  
- **Other shards**: No errors in shards 0–6 (only shard 7 has errors).  
- **Baseline noise**: No pre-incident patterns (e.g., "PRESENT FROM FILE START") are linked to the issue.  
- **Configuration changes**: No deploy/migration/flag events precede the incident.  

## Suggested next steps  
1. **Audit shard 7's database connection pool configuration** (e.g., max connections, timeout settings).  
2. **Monitor connection usage metrics** for shard 7 during peak hours to validate saturation.  
3. **Check query patterns** for shard 7: Is `key=user:celeb_8812` or `fanout=hot` triggering excessive load?  
4. **Validate fanout=hot logic**—could it be causing unintended query amplification?  
5. **Review logs for upstream services** (e.g., user service) to confirm if `user:celeb_8812` is a high-volume or anomalous key.
