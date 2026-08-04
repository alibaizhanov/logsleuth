## Symptom  
Repeated `TypeError: cannot read field 'expiry_ts' of null` in `normalize_quote` for partner `ratehub`, accompanied by schema validation warnings for null `quote.terms` fields.  

## Timeline  
- **2026-08-05T14:03:20.705Z**: First error occurs (`ERROR quotes-api TypeError...`).  
- **2026-08-05T14:03:21.258Z**: Schema validation warning for `quote.terms=null` appears.  
- **2026-08-05T14:09:54.198Z**: Error resurfaces during peak, with frequent `ERROR` and `WARN` lines.  
- **2026-08-05T14:10:04.649Z**: Last error logged before the log snippet ends.  

## Root cause hypothesis  
**quotes-api** processing logic for `ratehub` partner; **medium confidence**. Evidence includes:  
- "ERROR quotes-api TypeError: cannot read field 'expiry_ts' of null in normalize_quote (partner=ratehub payload field quote.terms=null)" (multiple instances).  
- "WARN quotes-api schema validation: unexpected null at quote.terms partner=ratehub" (correlates with the null `quote.terms` field causing the error).  

## Ruled out  
- **Baseline 200 status codes**: These are normal operation and do not indicate a failing component.  
- **Numeric trends**: No significant changes in latency or error rates pre-incident.  

## Suggested next steps  
1. **Validate `ratehub` payload schema**: Confirm if `quote.terms` is expected to be non-null and investigate why it’s null in incoming requests.  
2. **Check `normalize_quote` logic**: Ensure `expiry_ts` is properly guarded against null values (e.g., optional chaining or default values).  
3. **Monitor `ratehub` integration**: Identify if recent changes to the partner’s API or data pipeline introduced null `quote.terms` fields.  
4. **Review logs for upstream dependencies**: Check if any upstream service (e.g., ratehub’s API) is sending malformed data.  
5. **Implement schema validation enforcement**: Add strict validation to reject requests with null `quote.terms` to prevent downstream errors.
