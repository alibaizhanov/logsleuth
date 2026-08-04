## Symptom  
Kafka consumer lag on the "orders" topic spiked to ~37k messages, accompanied by frequent rebalances triggered by member `c-3` session timeouts, disrupting processing and increasing latency.  

## Timeline  
- **11:10:17.773Z**: `c-3` session timeout triggers rebalance.  
- **11:10:18.586Z**: Consumer lag on partition 6 reaches 21.8k.  
- **11:10:35.633Z**: Rebalance triggered again; lag on partition 10 reaches 22.4k.  
- **11:18:29.869Z**: Final rebalance triggered; lag on partition 9 reaches 37.6k.  
- **11:18:29.739Z**: Rebalance completes, generation jumps to 893.  

## Root cause hypothesis  
**Kafka consumer group rebalances caused by member `c-3` session timeout** (confidence: **medium**).  
- Evidence:  
  - `"kafka group orders-cg rebalance triggered: member c-3 session timed out (session.timeout.ms=10000)"` (multiple instances).  
  - `"kafka consumer lag topic=orders partition=<n> lag=<n>"` (lag grew from ~21k to ~37k).  
  - Rebalances coincided with lag spikes, suggesting `c-3`’s timeout caused partition reassignment, exacerbating lag.  

## Ruled out  
- **Baseline noise**: Pre-existing "kafka consumer lag" and "rebalance triggered" logs (present from file start) are not root causes.  
- **Memory/GC pauses**: While GC pauses (e.g., `gc pause=15247ms`) occurred, they are symptoms, not causes.  

## Suggested next steps  
1. **Investigate `c-3`’s session timeout root cause**: Check if it’s due to processing delays, network latency, or resource starvation (e.g., CPU/memory).  
2. **Review `session.timeout.ms` configuration**: Verify if the 10s threshold is appropriate for workload patterns.  
3. **Monitor consumer lag trends**: Deploy alerts for lag exceeding thresholds to prevent future rebalances.  
4. **Audit Kafka consumer group stability**: Check for recent configuration changes or topology shifts affecting `orders-cg`.  
5. **Test consumer resilience**: Simulate `c-3` failures to validate rebalance recovery and lag mitigation strategies.
