## Symptom  
The `ingest-consumer` service experienced repeated worker crashes and escalating consumer lag on partition 7 of the `events` topic, with protobuf parse errors causing failures to decode messages.  

## Timeline  
- **08:00:19.052Z**: Normal request handled (baseline).  
- **08:00:20.193Z**: Consumer lag spikes to 4350 (not advancing).  
- **08:00:26.824Z**: First "protobuf parse error: truncated varint" error occurs.  
- **08:00:26.102Z**: Worker crashes, restarting.  
- **08:00:42.121Z**: Same error reappears, triggering another crash.  
- **08:00:44.300Z**: Error persists, leading to repeated crashes and unresolved lag.  
- **08:14:32.660Z**: Consumer lag peaks at 21,300 (not advancing).  

## Root cause hypothesis  
**Ingest-consumer worker processing partition 7 of the events topic** — **medium confidence**. Evidence includes repeated "protobuf parse error: truncated varint" errors (first seen at 4% of file) and escalating consumer lag (6343 → 19571). The errors suggest corrupted or malformed data in the topic, causing the worker to crash and restart, preventing progress.  

## Ruled out  
- **Baseline noise**: Pre-existing "consumer lag" warnings and "protobuf parse error" entries (marked as present from file start) were not the root cause, as they did not escalate until the incident.  
- **Consumer configuration**: No config changes were logged in the CHANGE EVENTS section.  

## Suggested next steps  
1. **Inspect data integrity**: Check for corrupted or malformed messages in the `events` topic, especially around offset 90412 (repeatedly failing).  
2. **Validate protobuf schema**: Confirm the consumer’s schema version matches the producer’s, ensuring compatibility.  
3. **Monitor consumer recovery**: Track if repeated crashes lead to persistent backlog or further degradation.  
4. **Audit recent deployments**: Investigate if any unlogged changes (e.g., data pipeline updates) introduced malformed data.  
5. **Enhance error logging**: Add detailed context (e.g., message content, offset ranges) to future parse errors for faster diagnosis.
