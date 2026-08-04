## Symptom  
Doc-ingest experienced request timeouts due to unavailability of processing slots, coinciding with severe G1 Humongous Allocation GC pauses exceeding 1.5s.  

## Timeline  
- **09:43:28** First timeout: "request timed out waiting for processing slot"  
- **09:43:29** First long GC pause: "gc pause=1767ms cause=G1 Humongous Allocation"  
- **09:43:31** Second long GC pause: "gc pause=2695ms cause=G1 Humongous Allocation"  
- **09:43:38** Second timeout: "request timed out waiting for processing slot"  
- **09:52:05** Multiple consecutive timeouts and GC pauses (5 instances)  

## Root cause hypothesis  
**doc-ingest's G1 Humongous Allocation GC pauses** (confidence: medium). Evidence:  
- "gc pause=2695ms cause=G1 Humongous Allocation" (09:43:31)  
- "payload_bytes=11587327" (09:43:26) and growing payload trends (x30.7 increase)  
- Correlation between payload size growth and GC pause duration (45.6ms → 2280.8ms).  

## Ruled out  
- **Baseline GC pauses**: "G1 Evacuation Pause" (e.g., 09:43:17) were present pre-incident and typically <100ms.  
- **Memory leaks**: No evidence of sustained memory growth or OOM errors.  

## Suggested next steps  
1. Validate if recent payload size increases correlate with doc-ingest's memory configuration (e.g., heap size, G1 settings).  
2. Check if "processing slots" are a fixed limit, and whether slot exhaustion is tied to GC pauses (e.g., thread contention during GC).  
3. Review logs for "doc-ingest" thread pool saturation or queue backpressure signals.  
4. Monitor GC pause triggers: confirm if humongous allocations are due to large documents or internal data structures.  
5. Test GC tuning (e.g., `-XX:MaxGCPauseTimeMillis`, `-XX:G1HeapRegionSize`) to mitigate humongous allocation pauses.
