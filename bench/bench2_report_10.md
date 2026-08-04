## Symptom  
Auth-gw instance `api-3` repeatedly rejects tokens with "unknown signature scheme v2" errors, while `api-1` and `api-2` process tokens normally.  

## Timeline  
- **2026-08-06T16:20:00.693Z**: `feature.new_auth=true` applied to `api-1`, `api-2` (api-3 unreachable, retrying).  
- **2026-08-06T16:20:08.785Z**: First error: `api-3` rejects tokens with "unknown signature scheme v2" (feature.new_auth=false).  
- **2026-08-06T16:29:00.408Z**: Errors persist, with `api-3` intermittently recovering to "token ok" but later reverting to errors.  

## Root cause hypothesis  
**Failed config rollout to `api-3`**, leaving it with `feature.new_auth=false` while other instances have it enabled. Confidence: **medium**.  
- Evidence: The config rollout attempted to enable `feature.new_auth=true` for `api-3` but marked it as unreachable ("will retry: never"). Subsequent errors show `api-3` still has `feature.new_auth=false`, causing it to reject tokens using the new v2 scheme.  

## Ruled out  
- **Other instances (`api-1`, `api-2`)**: No errors, indicating the issue is isolated to `api-3`.  
- **Baseline noise**: Pre-existing errors (marked "PRESENT FROM FILE START") are unrelated, as they occur before the config rollout and do not involve `api-3`.  

## Suggested next steps  
1. **Verify `api-3`'s config status**: Confirm whether `feature.new_auth` is still disabled post-rollout.  
2. **Check rollout retry status**: Investigate why `api-3` was unreachable during the initial rollout and ensure the config is applied.  
3. **Validate auth scheme compatibility**: Ensure `api-3`'s auth-gw is configured to accept v2 tokens when `feature.new_auth=true`.  
4. **Monitor rollback/retry mechanisms**: Confirm the rollout system handles unreachable replicas correctly to prevent partial configuration states.  
5. **Test token validation**: Simulate a token with v2 signature on `api-3` to confirm the rejection is due to `feature.new_auth=false`.
