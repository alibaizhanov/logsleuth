## Symptom  
Multiple `doc-ingest` request timeouts and prolonged G1 GC pauses (up to ~3.8s) occurred between 09:43:28Z and 09:52:05Z.  

## Timeline  
- **09:43:28Z**: First timeout: `doc-ingest request timed out waiting for processing slot`  
- **09:43:29Z**: First G1 Humongous Allocation GC pause (1767ms)  
- **09:43:38Z**: Second timeout  
- **09:43:44Z**: Third timeout  
- **09:44:00Z**: Fourth timeout  
- **09:52:05Z**: Final timeout with GC pause (3527ms)  

## Root cause hypothesis  
**G1 Humongous Allocation GC pauses in `doc-ingest` JVM** — **medium confidence**  
Evidence:  
- "G1 Humongous Allocation" GC pauses grew from 1.8s to 3.8s (line 29% of file).  
- Payload bytes increased 30x (373KB → 11.5MB) during the incident (numeric trend).  
- Timeouts correlated with GC pauses, suggesting processing slots were starved during GC cycles.  

## Ruled out  
- **Baseline G1 Evacuation Pauses**: Earlier "G1 Evacuation Pause" events (e.g., 37ms) were normal and not correlated with timeouts.  
- **Static payload sizes**: Pre-incident payload_bytes were ~373KB (line 28% of file), far below the 11.5MB peak.  

## Suggested next steps  
1. Audit `doc-ingest` JVM G1 GC settings (e.g., `-XX:MaxGCPauseTimeMillis`, `-XX:G1HeapRegionSize`) for humongous allocation handling.  
2. Monitor processing slot utilization during GC pauses to confirm starvation.  
3. Investigate why payload_bytes spiked 30x during the incident (e.g., data ingestion pipeline changes).  
4. Check for memory leaks or unbounded object allocation in `doc-ingest` code.  
5. Validate if recent GC pause patterns (e.g., 3.8s) are reproducible under load.
