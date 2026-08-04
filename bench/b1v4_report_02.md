## Symptom  
TLS handshake failures and SSL verification errors occur for `api.corp.com`, causing upstream probe failures and client connection issues.  

## Timeline  
- **2026-08-04T09:30:00.689Z**: Gateway loads certificate for `api.corp.com` with `notAfter=2026-08-04T10:00:00Z`.  
- **2026-08-04T10:00:00.137Z**: Normal request handled by gateway.  
- **2026-08-04T10:00:00.862Z**: First upstream probe failure: SSL verification error for `api.corp.com`.  
- **2026-08-04T10:00:02.062Z**: First TLS handshake failure: certificate expired/invalid.  
- **2026-08-04T10:25:00.510Z**: Last TLS handshake failure for client 9.  

## Root cause hypothesis  
**Expired certificate for `api.corp.com`**; confidence: **high**.  
Evidence: The certificate loaded at 09:30 had `notAfter=2026-08-04T10:00:00Z`, and TLS handshake failures/SSL verification errors began exactly at 10:00:02Z, matching the certificate’s expiration time.  

## Ruled out  
- **Baseline TLS handshakes**: No prior TLS errors in the log (errors first appear at 28% of the file).  
- **Upstream service outages**: Probes failed due to SSL verification, not service unavailability.  
- **Network issues**: No mention of dropped packets or connectivity loss; errors are TLS-specific.  

## Suggested next steps  
1. Verify the validity period of the `api.corp.com` certificate in the gateway’s trust store.  
2. Check if the certificate was manually replaced or renewed after 10:00:00Z (e.g., via automation or human intervention).  
3. Implement alerts for certificate expiration dates in the gateway’s configuration.  
4. Validate if the upstream service (`api.corp.com`) is configured to accept expired certificates (unlikely, but possible).  
5. Review logs for any certificate rotation activity around 09:30Z.
