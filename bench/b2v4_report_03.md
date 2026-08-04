## Symptom  
A surge of customer complaints about duplicate charges occurred, with 89 duplicate charge errors logged within a short timeframe, followed by a spike in support-api error handling.  

## Timeline  
- **2026-11-01T01:30:00.050Z**: `billing-cron` job `daily_charges` started.  
- **2026-11-01T02:31:01.768Z**: `billing-cron` job `daily_charges` finished, charged=120.  
- **2026-11-01T03:00:01.109Z**: First duplicate charge error reported by `support-api`.  
- **2026-11-01T03:03:06.010Z**: Last duplicate charge error reported by `support-api`.  

## Root cause hypothesis  
**billing-cron job `daily_charges`**; **confidence: medium**. Evidence includes:  
- The `daily_charges` job ran normally (started at 01:30, finished at 02:31), but its output (charge records) triggered 89 duplicate charge errors in `support-api` shortly afterward.  
- No errors were logged from `billing-cron` itself, suggesting the job completed successfully but produced invalid or redundant charge records.  

## Ruled out  
- **Baseline INFO logs** (e.g., `charged account=<id>`): These were present before the incident and are likely noise, not causative.  
- **Other RARE events** (e.g., scheduler logs): No direct link to the duplicate charge errors.  

## Suggested next steps  
1. **Audit `daily_charges` job logic**: Verify if it inadvertently generated duplicate charges (e.g., missing deduplication logic).  
2. **Check `support-api` charge validation**: Confirm if it failed to detect duplicates due to race conditions or stale data.  
3. **Correlate charge IDs**: Cross-reference charge IDs from `billing-cron` logs with `support-api` errors to identify duplicates.  
4. **Monitor for replayed charges**: Check if the `daily_charges` job was retried or rescheduled after the initial run.  
5. **Review recent code changes**: Identify if any recent updates to `billing-cron` or `support-api` introduced logic errors.
