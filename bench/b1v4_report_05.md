## Symptom  
Severe latency spikes (up to 5.3s) and disk I/O utilization exceeding 73% coincided with slow query warnings and degraded database performance.  

## Timeline  
- **2026-08-04T02:00:01.424Z**: Disk I/O utilization reached 97% with 503ms read wait.  
- **2026-08-04T02:00:05.583Z**: First "orders db query latency" exceeded 2s (2042ms).  
- **2026-08-04T02:00:08.989Z**: First slow-log warning for "SELECT ... FOR UPDATE" (2483ms).  
- **2026-08-04T02:00:24.882Z**: Second slow-log warning (5266ms), with disk I/O at 99%.  
- **2026-08-04T02:06:19.501Z**: Peak latency reached 2953ms for "orders db query".  

## Root cause hypothesis  
**pg_basebackup cron job** (confidence: high). The backup process likely caused I/O contention on `db-1`, leading to elevated disk utilization and slow query performance. Evidence includes:  
- "cron pg_basebackup started" (line 801) coinciding with the incident onset.  
- Disk I/O utilization spiked to 97–99% during the same timeframe.  
- Slow queries ("SELECT ... FOR UPDATE") correlated with high read_wait times.  

## Ruled out  
- **Baseline noise patterns** (e.g., "orders db query latency" present before the incident) are not root causes.  
- **Other components**: No evidence of thread exhaustion, queue backpressure, or memory issues in the logs.  

## Suggested next steps  
1. **Verify pg_basebackup scheduling**: Confirm if backups are configured to run during peak hours and adjust timing.  
2. **Monitor I/O during backups**: Use tools like `iostat` or cloud provider metrics to isolate I/O contention.  
3. **Optimize slow queries**: Analyze "SELECT ... FOR UPDATE" queries for locks or indexing issues.  
4. **Test I/O class isolation**: Ensure `io_class=best-effort` for backups doesn’t interfere with production workloads.  
5. **Implement backup throttling**: Use tools like `pg_pitr` or cloud-native backup solutions to reduce I/O impact.
