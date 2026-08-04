## Symptom  
High inference latency in `ml-scorer` (up to 5s) and gateway timeouts triggering fallback ranking, correlating with severe CPU throttling (94% throttled_pct).  

## Timeline  
- **2026-08-05T22:15:00.816Z**: `ml-scorer-6b9d` pod evicted from node-a1 (spot reclaim), rescheduled to node-b7 with CPU limit 500m (was 4000m).  
- **2026-08-05T22:15:21.825Z**: First inference latency spike to 178ms.  
- **2026-08-05T22:15:30.700Z**: Inference latency jumps to 83ms, followed by 2128ms (4.5s) and 4077ms (8.2s) latencies.  
- **2026-08-05T22:26:45.577Z**: Gateway timeout error triggers fallback ranking.  
- **2026-08-05T22:26:49.358Z**: CPU throttling peaks at 94% (840 periods).  

## Root cause hypothesis  
**CPU limit reduction on node-b7 after pod eviction**; confidence: **high**.  
Evidence:  
- The `ml-scorer-6b9d` pod was evicted from node-a1 (spot reclaim) and rescheduled to node-b7 with **CPU limit 500m** (originally 4000m).  
- CPU throttling metrics (`cpu_throttled_periods`, `throttled_pct`) **exponentially increased** from 23.1 → 91.6% and 223.6 → 840 periods, correlating with the pod migration.  
- Inference latency spikes and gateway timeouts directly follow the CPU throttling surge.  

## Ruled out  
- **Baseline noise**: "PRESENT FROM FILE START" patterns (e.g., generic CPU throttling) are not the cause.  
- **Model issues**: No evidence of model errors or version changes.  
- **Network issues**: No dropped packets or latency spikes in gateway logs.  

## Suggested next steps  
1. **Verify node-b7’s CPU capacity**: Confirm if node-b7’s CPU resources (cores, limits) are sufficient for `ml-scorer` workloads.  
2. **Audit pod scheduling**: Check if the pod was rescheduled to node-b7 due to spot instance reclaim, and whether the CPU limit was inadvertently reduced.  
3. **Monitor resource contention**: Track CPU usage and throttling metrics for `ml-scorer` pods post-migration.  
4. **Test CPU limits**: Replicate the scenario with a temporary CPU limit of 500m to validate throttling behavior.  
5. **Implement auto-scaling**: Ensure `ml-scorer` can scale horizontally or adjust CPU limits dynamically during node reclaims.
