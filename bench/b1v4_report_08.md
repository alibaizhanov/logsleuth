## Symptom  
Reports-svc experienced request timeouts and escalating latency, with threadpool queues growing to 808+ tasks, causing delays in handling `/report` and `/v1/items` endpoints.  

## Timeline  
- **2026-08-04T17:30:00.641Z**: `reports-svc` log sink changed to NFS (rare event).  
- **2026-08-04T17:33:18.002Z**: Threadpool queued=808, active=40/40.  
- **2026-08-04T17:33:27.469Z**: First NFS server timeout warning.  
- **2026-08-04T17:33:29.921Z**: First "request timed out waiting for worker thread" warning.  
- **2026-08-04T17:42:15.588Z**: Threadpool queued=827, with repeated NFS timeout warnings.  

## Root cause hypothesis  
**NFS logstore configuration change** (confidence: high). The log sink switch to NFS caused write failures, blocking worker threads and triggering timeouts. Evidence:  
- "nfs client logstore: server not responding" warnings (first seen at 28% of file, coinciding with the log sink change).  
- "reports-svc request timed out waiting for worker thread" errors (first seen at 28% of file, correlating with NFS write failures).  
- Threadpool queued tasks grew from 0 to 808+ (160 samples) post-log-sink change.  

## Ruled out  
- **Threadpool size limits**: The threadpool was configured to 40 active threads, but the issue stemmed from **write blocking** (not thread exhaustion).  
- **Baseline noise**: "PRESENT FROM FILE START" patterns (e.g., queued=0) were pre-existing and not directly tied to the incident.  

## Suggested next steps  
1. **Verify NFS server availability** and network connectivity for the logstore.  
2. **Review logs for NFS write errors** in the `reports-svc` and downstream systems.  
3. **Monitor threadpool metrics** (queued/active) during log sink changes to detect blocking operations.  
4. **Test log sink failover** mechanisms to prevent write blocking from impacting request handling.  
5. **Evaluate log retention policies** to ensure NFS storage capacity and performance are adequate.
