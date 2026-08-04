## Symptom  
The `ingest-consumer` experienced repeated protobuf parse errors on partition 7, leading to worker crashes and escalating consumer lag.  

## Timeline  
- **08:00:04.336Z**: `WARN` consumer lag=4050 (not advancing) on partition 7.  
- **08:00:07.014Z**: `INFO` consumer started resuming partition 7 at offset 90412.  
- **08:00:07.191Z**: `ERROR` protobuf parse error at offset 90412, triggering a `FATAL` worker crash.  
- **08:00:16.242Z**: Second `FATAL` crash after resuming partition 7 at the same offset.  
- **08:14:32.660Z**: Consumer lag on partition 7 reached 21,275 (not advancing).  
- **08:14:44.541Z**: Third `FATAL` crash after resuming partition 7 at offset 90412.  

## Root cause hypothesis  
**Ingest-consumer's protobuf parser failure on partition 7 offset 90412** (confidence: **medium**).  
Evidence:  
- "ERROR ingest-consumer failed to decode message... truncated varint" (line 2026-08-05T08:00:07.191Z)  
- "FATAL ingest-consumer worker crashed, restarting" (line 2026-08-05T08:00:07.864Z)  
- Repeated crashes at the same offset suggest corrupted or malformed data in this specific message.  

## Ruled out  
- **Baseline noise**: Pre-existing "consumer lag" and "protobuf parse error" patterns (from file start) are not the root cause; they are symptoms of the same underlying issue.  
- **Resource exhaustion**: No logs indicate threads/queues/memory being exhausted.  

## Suggested next steps  
1. Inspect the message at offset 90412 in partition 7 for corruption or malformed protobuf data.  
2. Validate if recent changes to the protobuf schema or data ingestion pipeline introduced parsing issues.  
3. Monitor consumer recovery behavior and check if the same offset reappears after restarts.  
4. Review Kafka topic retention policies to ensure old messages aren’t being reprocessed.  
5. Add idempotency checks for critical messages to prevent cascading failures.
