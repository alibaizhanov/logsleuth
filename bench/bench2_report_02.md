## Symptom  
The `thumb-svc` encountered repeated "No space left on device" errors when writing thumbnails to `/var/cache/thumbs/`, indicating inode exhaustion rather than disk space depletion.  

## Timeline  
- **10:39:24Z**: First `OSError 28` error for `/var/cache/thumbs/2431984.tmp`  
- **10:39:27Z**: Second error for `/var/cache/thumbs/8254904.tmp`  
- **10:44:02Z**: `node-exporter` reports `inodes_used=100%` on `/var`  

## Root cause hypothesis  
**Inode exhaustion in `/var` due to unbounded thumbnail caching in `thumb-svc`**; confidence: **high**  
- Evidence: The `thumb-svc` logs show repeated failures writing to `/var/cache/thumbs/` files, coinciding with `node-exporter` reporting `inodes_used=100%` (e.g., `2026-08-05T10:44:02.328Z`).  
- The `thumb-svc` generates thumbnails and caches them in `/var/cache/thumbs/`, creating files that consume inodes. No disk space exhaustion is observed (`free=412GB`), confirming the issue is inode-related.  

## Ruled out  
- **Disk space depletion**: Logs show `free=412GB` in `/var` during the incident, ruling out disk space as the cause.  
- **Baseline noise**: No pre-existing patterns (e.g., "PRESENT FROM FILE START") are implicated; the errors are new and monotonic.  

## Suggested next steps  
1. **Verify inode limits**: Check `/var` filesystem inode limits and confirm they are insufficient for the expected thumbnail workload.  
2. **Audit `thumb-svc` caching**: Investigate why `thumb-svc` generates so many thumbnails in `/var/cache/thumbs/` (e.g., misconfigured cache retention, bug in thumbnail generation).  
3. **Implement inode monitoring**: Add alerts for `inodes_used` nearing 100% on `/var` to prevent future outages.  
4. **Adjust cache settings**: Configure `thumb-svc` to use a dedicated, inode-abundant volume for thumbnails or limit cache size.  
5. **Review retention policies**: Ensure old thumbnails are purged periodically to prevent inode exhaustion.
