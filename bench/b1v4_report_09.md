## Symptom  
A NullPointerException in `PriceFormatter.apply(discount=null)` caused 50x errors in the `/product` endpoint, exclusively affecting traffic routed to the new build `9e1c77`.  

## Timeline  
- **2026-08-04T19:15:00.107Z**: Canary rollout initiated, 10% traffic directed to build `9e1c77` (main build `5b0a12`).  
- **2026-08-04T19:15:01.173Z**: First error logged for build `9e1c77`: `NullPointerException` in `PriceFormatter.apply(discount=null)`.  
- **2026-08-04T19:23:05.865Z**: Error rate spikes, with multiple consecutive `NullPointerException` errors for build `9e1c77`.  

## Root cause hypothesis  
**New build `9e1c77` (canary rollout)** — **High confidence**. The `NullPointerException` in `PriceFormatter.apply(discount=null)` is exclusive to build `9e1c77`, which was deployed via canary rollout. No errors occurred for the main build `5b0a12` during the same timeframe.  

## Ruled out  
- **Baseline noise**: The `50x ERROR` pattern (`NullPointerException` in `PriceFormatter`) was present from the file start but only affected build `5b0a12` pre-rollout.  
- **Other components**: No logs indicate thread exhaustion, queue backpressure, or memory issues.  

## Suggested next steps  
1. **Roll back the canary rollout** for build `9e1c77` to isolate the issue.  
2. **Audit changes in build `9e1c77`** (e.g., `PriceFormatter` logic, dependency updates) to identify the root cause of `discount=null`.  
3. **Validate input handling** for the `/product` endpoint to ensure `discount` parameters are never null in production traffic.  
4. **Implement circuit breakers or fallbacks** for `PriceFormatter` to prevent cascading failures from null inputs.  
5. **Monitor error rates** for build `9e1c77` in staging environments to confirm the issue is reproducible and not environment-specific.
