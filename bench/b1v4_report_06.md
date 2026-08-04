## Symptom  
The `inventory-svc` repeatedly failed to connect to `warehouse-api` with "too many open files (EMFILE)" errors, indicating exhaustion of file descriptors.  

## Timeline  
- **2026-08-04T16:00:00.514Z**: `inventory-svc` upgraded `http-client` from 4.2.0 → 5.0.0 (changelog: connection reuse rewritten).  
- **2026-08-04T16:14:53.344Z**: First EMFILE error observed.  
- **2026-08-04T16:14:54.275Z**: `fd_count` reached 1965.  
- **2026-08-04T16:17:34.692Z**: `fd_count` spiked to 2128 during peak incident.  

## Root cause hypothesis  
**http-client 5.0.0 upgrade introduced connection reuse bug**; confidence: **high**.  
Evidence:  
- The upgrade coincided with the first EMFILE errors (line 1).  
- `fd_count` and `established`/`idle_never_closed` metrics grew monotonically (numeric trends), indicating unbounded connection pooling.  
- The new `http-client` version's "connection reuse rewritten" changelog entry likely broke proper FD recycling.  

## Ruled out  
- **Baseline noise**: `established` and `idle_never_closed` trends were present pre-incident but not tied to the EMFILE errors.  
- **Other components**: No other services or errors were implicated in the logs.  

## Suggested next steps  
1. **Audit `http-client` 5.0.0 changelog** for connection pooling or FD management regressions.  
2. **Roll back `http-client` to 4.2.0** in staging to confirm resolution.  
3. **Monitor `fd_count` and connection pool metrics** post-rollback to validate fix.  
4. **Implement FD limit alerts** to catch similar issues proactively.  
5. **Review upgrade process** for missing configuration updates (e.g., pool size limits).
