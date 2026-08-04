## Symptom  
High latency and connection pool saturation errors in `feed-api` queries targeting shard=7, with multiple warnings indicating "fanout=hot" and queueing.  

## Timeline  
- **2026-08-05T19:01:55.053Z**: First error for shard=7 (latency=1730ms).  
- **2026-08-05T19:01:55.582Z**: Latency spikes to 3880ms for shard=7.  
- **2026-08-05T19:02:00.788Z**: Multiple consecutive warnings for shard=7 (latency up to 3236ms).  
- **2026-08-05T19:08:12.641Z**: First `ERROR` for shard=7: "connection pool saturated, queueing".  
- **2026-08-05T19:08:14.846Z**: Second `ERROR` for shard=7: "connection pool saturated, queueing".  

## Root cause hypothesis  
**Component**: `feed-api` shard=7 connection pool  
**Confidence**: Medium  
**Evidence**:  
- "ERROR feed-api shard=7 connection pool saturated, queueing" (quoted verbatim).  
- All error-like lines are tied to shard=7 (100% of errors).  
- Latency for shard=7 grew from 197ms to 1569ms (x8.0) and shard usage increased from 3.6 to 5.7.  

## Ruled out  
- **Other shards**: No errors or latency spikes observed for shards 0–6.  
- **Baseline noise**: "PRESENT FROM FILE START" patterns (e.g., INFO-level latency) are not tied to the incident.  
- **Fanout=hot**: While present in some warnings, it is a symptom, not the root cause.  

## Suggested next steps  
1. **Investigate shard=7 connection pool configuration**: Check max pool size, timeout settings, and whether it’s misaligned with traffic patterns.  
2. **Analyze queries for shard=7**: Identify if specific queries (e.g., `key=user:celeb_8812`) are causing excessive fanout or resource contention.  
3. **Monitor shard=7’s queue depth**: Determine if the connection pool saturation is due to backpressure from downstream systems or internal bottlenecks.  
4. **Review recent changes to shard=7**: Even though no RARE events were found, check for untracked config updates or schema changes.  
5. **Scale or optimize shard=7’s resources**: Temporarily increase connection pool size or offload heavy queries to other shards.
