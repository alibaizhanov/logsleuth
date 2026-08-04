## Symptom  
Repeated `jwt validation failed: token used before issued (iat in future)` errors on `api-2`, with no similar issues on other hosts.  

## Timeline  
- **2026-08-04T13:00:03.061Z**: First `ERROR auth host=api-2` JWT validation failure.  
- **2026-08-04T13:00:00.962Z**: `WARN ntpd host=api-2` reports no NTP servers found for synchronization.  
- **2026-08-04T13:11:13.496Z**: Last JWT error on `api-2` before logs end.  

## Root cause hypothesis  
**ntpd failure on api-2**; confidence: **high**.  
Evidence: The rare `ntpd` warning at 13:00:00.962Z directly precedes the first JWT error. This indicates clock drift or synchronization failure, which would cause tokens issued by other services (e.g., `auth`) to have invalid `iat` timestamps when validated by `api-2`.  

## Ruled out  
- **Baseline JWT errors**: The `jwt validation failed` errors are present in logs *before* the incident (marked "PRESENT FROM FILE START"), but they only target `api-2` during the incident, suggesting they are symptoms, not root cause.  
- **Other hosts**: `api-1` and `api-3` show no errors, isolating the issue to `api-2`.  

## Suggested next steps  
1. Verify `ntpd` configuration and connectivity on `api-2` to ensure NTP servers are reachable.  
2. Check system clock drift on `api-2` and investigate why NTP synchronization failed.  
3. Review token issuance timestamps from the `auth` service to confirm they are generated correctly.  
4. Monitor if the issue recurs after fixing NTP, and validate clock synchronization across all hosts.  
5. Implement alerts for NTP failure warnings to catch such issues proactively.
