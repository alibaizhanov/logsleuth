## Symptom  
The `quotes-api` service encountered repeated `TypeError` exceptions when accessing the non-existent `expiry_ts` field on a `null` `quote.terms` object, specifically for partner `ratehub`. Schema validation warnings also indicated unexpected `null` values in the `quote.terms` field.  

## Timeline  
- **2026-08-05T14:03:20.705Z**: First occurrence of `TypeError` due to `quote.terms=null` in `normalize_quote` for `ratehub`.  
- **2026-08-05T14:03:21.258Z**: Schema validation warning for `quote.terms=null` from `ratehub`.  
- **2026-08-05T14:09:54.198Z–14:10:04.649Z**: Errors persisted, with 8 additional `TypeError` and `WARN` entries for `ratehub` payload issues.  

## Root cause hypothesis  
**Failing component**: `ratehub` data pipeline feeding into `quotes-api`  
**Confidence**: Medium  
**Evidence**:  
- Multiple `TypeError` and `WARN` logs explicitly state `quote.terms=null` in payloads from `ratehub` (e.g., `2026-08-05T14:03:20.705Z ERROR quotes-api TypeError: cannot read field 'expiry_ts' of null in normalize_quote (partner=ratehub payload field quote.terms=null)`).  
- Schema validation warnings confirm the presence of invalid `null` values in `quote.terms` (e.g., `2026-08-05T14:03:21.258Z WARN quotes-api schema validation: unexpected null at quote.terms partner=ratehub`).  

## Ruled out  
- **No recent deploy/migration/config change**: No change events were logged pre-incident.  
- **Memory/thread exhaustion**: No logs indicate resource exhaustion or queue backpressure.  
- **Baseline noise**: The `quote.terms=null` errors are not marked as PRESENT FROM FILE START and are not part of historical baseline patterns.  

## Suggested next steps  
1. **Validate data from `ratehub`**: Confirm if `quote.terms` is being sent as `null` in payloads and investigate why the data pipeline is producing invalid inputs.  
2. **Update schema validation**: Add explicit checks for `null` values in `quote.terms` to prevent schema validation warnings and subsequent errors.  
3. **Add defensive null checks**: Modify `normalize_quote` to handle `null` `quote.terms` gracefully (e.g., default values or logging).  
4. **Monitor partner data integrity**: Implement alerts for unexpected `null` values in critical fields like `quote.terms` from `ratehub`.  
5. **Review API contract**: Ensure `ratehub` aligns with the expected schema for `quote.terms` to prevent future disruptions.
