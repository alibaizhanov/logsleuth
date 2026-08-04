## Symptom  
Repeated "No space left on device" errors in `thumb-svc` writes to `/var/cache/thumbs/` tmp files, coinciding with inode exhaustion in `/var`.  

## Timeline  
- **10:39:24Z**: First `OSError 28` write failure in `thumb-svc`.  
- **10:39:27Z**: Second `OSError 28` error.  
- **10:44:02Z**: `node-exporter` reports `/var` inodes_used=100%.  
- **10:44:12Z**: Final `OSError 28` error with inodes_used=100%.  

## Root cause hypothesis  
**thumb-svc thumbnail generation consuming inodes in `/var`**; confidence: **medium**.  
Evidence:  
- `ERROR thumb-svc write failed...OSError 28 No space left on device` (multiple instances).  
- `node-exporter` confirms `/var` inodes_used=100% during error spikes.  

## Ruled out  
- **Baseline disk usage**: `/var` free=412GB (used=48%) pre-incident, which is not the direct cause.  
- **Other services**: No logs indicate other components triggering inode exhaustion.  

## Suggested next steps  
1. Verify `/var` inode limits and resize partition if necessary.  
2. Audit `thumb-svc` thumbnail caching logic to prevent inode exhaustion (e.g., cleanup old files).  
3. Monitor `/var` inodes in real-time to detect future spikes.  
4. Investigate if recent changes increased thumbnail generation volume.  
5. Implement alerting for inodes_used > 95% on `/var`.
