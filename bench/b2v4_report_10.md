## Symptom  
Auth-gw instance `api-3` repeatedly rejects tokens with signature scheme `v2` due to an unknown scheme, despite `feature.new_auth=false` being explicitly set on the replica.  

## Timeline  
- **2026-08-06T16:20:00.693Z**: `config-rollout` applies `feature.new_auth=true` to `api-1`, `api-2` (notably excluding `api-3`), which becomes unreachable and will retry forever.  
- **2026-08-06T16:20:08.785Z**: First `ERROR` for `api-3` rejecting `v2` tokens, with `feature.new_auth=false` explicitly noted.  
- **2026-08-06T16:29:02.986Z**: `api-3` continues to reject `v2` tokens intermittently, with no resolution.  

## Root cause hypothesis  
**Failing component**: `api-3` auth-gw instance; **Confidence**: High  
**Evidence**:  
- The `config-rollout` log explicitly states `api-3` is unreachable during rollout and will retry: never.  
- All `ERROR` lines for `api-3` show `feature.new_auth=false`, indicating it was not updated to handle the new `v2` scheme, while `api-1`/`api-2` (which received the rollout) process `v2` tokens successfully.  

## Ruled out  
- **Baseline noise**: The `unknown signature scheme v<n>` errors (present from file start) are unrelated, as they occur on `api-1`/`api-2` with `feature.new_auth=false` (pre-rollout).  
- **Other instances**: `api-1`/`api-2` show no errors, ruling out systemic auth-gw issues.  

## Suggested next steps  
1. Verify why `api-3` was excluded from the `config-rollout` and whether its unreachable state during rollout caused the feature flag to remain disabled.  
2. Check if `api-3`’s auth-gw configuration explicitly disables `v2` or has conflicting settings overriding the feature flag.  
3. Validate the `config-rollout` retry mechanism for `api-3` to ensure it eventually receives the updated configuration.  
4. Review logs for `api-3` during the rollout window to confirm if the feature flag was ever applied or if the instance was permanently skipped.  
5. Test `api-3` with a token using `v2` scheme to confirm the rejection is due to the feature flag state, not a code bug.
