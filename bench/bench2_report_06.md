## Symptom  
The `ml-scorer` component's inference latency spiked to over 5 seconds, triggering CPU throttling and gateway timeouts, forcing fallback ranking.  

## Timeline  
- **22:15:21** `ml-scorer` inference latency: 178ms (baseline).  
- **22:15:30.700Z** First latency spike to 2128ms (WARN).  
- **22:15:40.750Z** Latency jumps to 4676ms (WARN).  
- **22:26:45.577Z** Gateway times out after 5000ms, using fallback.  
- **22:26:49.358Z** CPU throttled_pct reaches 94% (peak).  

## Root cause hypothesis  
**ml-scorer (ranker-v9 model)** — **High confidence**. The model's inference latency increased monotonically, correlating with CPU throttling (`cpu_throttled_periods` grew 3.8x). The latency spikes (e.g., "inference latency=5636ms") directly preceded gateway timeouts.  

## Ruled out  
- **Baseline inference latencies** (e.g., "inference latency=178ms") were normal and predated the incident.  
- **No recent changes** (deployments/migrations/config) were logged to explain the drift.  

## Suggested next steps  
1. **Investigate resource constraints**: Check if `ml-scorer` is hitting CPU limits or memory bottlenecks.  
2. **Profile model performance**: Validate if `ranker-v9` has degraded (e.g., data drift, inefficient code).  
3. **Monitor CPU throttling triggers**: Identify if sustained high load or thermal throttling caused the spike.  
4. **Check for unhandled backpressure**: Verify if downstream systems (gateway) are contributing to request volume spikes.  
5. **Audit model retraining/scale**: Confirm if the model was recently retrained or scaled without proper validation.
