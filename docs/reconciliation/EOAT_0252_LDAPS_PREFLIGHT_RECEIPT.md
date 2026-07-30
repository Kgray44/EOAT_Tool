# EOAT Atlas 0.25.3 LDAPS production preflight receipt

Date: 2026-07-30
Operation: anonymous, read-only preflight; no directory credentials supplied
or attempted.
Endpoint: `ldaps://gwplastics.com:636`

| Check | Result |
| --- | --- |
| DNS | 6 unique addresses resolved; addresses are retained only as 16-character SHA-256 fingerprints |
| TCP | Connected to 4 distinct resolved IPv4 endpoints within the five-second bound |
| TLS / certificate chain / hostname | Not reached: all four TCP peers reset the connection during TLS negotiation (`ConnectionResetError`) before presenting a certificate |
| Validity dates, subject, issuer, SAN, signature | Not available; no certificate was presented |
| Anonymous RootDSE / LDAP response | Not attempted after failed verified TLS handshake |
| Naming contexts / controls | Not available because RootDSE was not reachable |
| Round-robin consistency | All four tested endpoints showed the same reset-before-certificate behavior; certificate consistency remains unproven |

The preflight implementation uses the platform trust store, hostname
verification for `gwplastics.com`, and no fallback mode. It did **not** bypass
certificate validation or make an unauthenticated plaintext LDAP attempt.

Sanitized endpoint fingerprints: `bfc6f85805fc8af8`, `f919835325e81ee0`,
`a251078c3266ef12`, `18eb4eaa4f147cee`.
