## Symptom  
Repeated `rate_limited` errors from the `paylink` provider, causing retry attempts and 429 HTTP status codes during checkout operations.  

## Timeline  
- **2026-08-04T12:00:00.769Z**: Traffic cutover complete: region `eu-1` routes through `provider=paylink` (volume x2.1).  
- **2026-08-04T12:00:13.515Z**: First `rate_limited` retry attempt (attempt=5).  
- **2026-08-04T12:09:44.063Z**: First `ERROR` with `status=429` and `Retry-After=30`.  
- **2026-08-04T12:09:48.432Z**: Subsequent `ERROR` with `status=429` and `Retry-After=30`.  
- **2026-08-04T12:09:53.150Z**: Final `ERROR` with `status=429` and `Retry-After=30`.  

## Root cause hypothesis  
**Paylink provider rate limiting after cutover**; confidence: **medium**.  
Evidence:  
- "2026-08-04T12:00:00.769Z INFO traffic cutover complete: region eu-1 now routes through provider=paylink (volume x2.1)" (line 1)  
- "2026-08-04T12:00:13.515Z WARN checkout retry scheduled attempt=5 reason=rate_limited provider=paylink"  
- "2026-08-04T12:09:44.063Z ERROR checkout paylink POST /charge status=429 Retry-After=30 latency=232ms"  

## Ruled out  
- **Pre-existing rate limiting warnings**: "207x [PRESENT FROM FILE START] <ts>.<n>Z WARN checkout retry scheduled attempt=<n> reason=rate_limited provider=paylink" — these were baseline noise and did not escalate to 429 errors.  
- **Memory/thread exhaustion**: No logs indicate resource exhaustion or queue backpressure.  

## Suggested next steps  
1. Verify `paylink`'s rate limits and ensure the cutover did not trigger unexpected volume spikes.  
2. Review retry logic for `/charge` endpoints to avoid excessive retries during rate limiting.  
3. Check if `paylink`'s `Retry-After` headers are being respected and adjust client-side backoff strategies if needed.  
4. Monitor `paylink`'s API health and latency during peak hours to detect potential upstream issues.  
5. Validate if the cutover configuration included proper traffic shaping or rate limit adjustments for `paylink`.
