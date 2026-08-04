## Symptom  
Search-backend health flapping and escalating memory usage (RSS/heap) coincided with frequent Envoy configuration reloads, leading to unstable service behavior.  

## Timeline  
- **20:44:53** – First instance i-04 health flapping detected (2s cycle).  
- **20:44:55** – Envoy memory RSS/heap at 215MB/150MB, config_reloads_total=524.  
- **20:45:48** – Envoy memory RSS/heap peaks at 312MB/219MB, config_reloads_total=1674.  
- **20:55:48** – Peak memory and config reloads persist, flapping continues.  

## Root cause hypothesis  
**search-backend service discovery misconfiguration or instability**; confidence: **medium**. Evidence:  
- "service-discovery search-backend health flapping: instance i-04 alternating healthy/unhealthy every ~2s" (multiple logs).  
- "envoy memory rss=312MB heap=219MB config_reloads_total=1674" (peak metrics).  
- "envoy cds: update rejected then accepted" flaps correlated with memory growth.  

## Ruled out  
- **Baseline noise**: "update rejected then accepted" flaps were present pre-incident (PRESENT FROM FILE START).  
- **Memory exhaustion**: No logs indicate OOM; RSS/heap growth was gradual, not abrupt.  

## Suggested next steps  
1. Audit service-discovery config for `search-backend` to verify health check intervals/tolerances.  
2. Check envoy logs for correlation between config reloads and upstream service failures.  
3. Monitor search-backend instance i-04 for application-level errors or warmup failures.  
4. Validate if memory growth is due to cached config objects or leaks via heap dumps.  
5. Replicate flapping behavior in staging to isolate service discovery vs. application root causes.
