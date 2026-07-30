# Remaining IT inputs for EOAT Atlas 0.25.3 LDAPS

Connectivity is partially proven: DNS resolution and TCP reachability to the
approved round-robin endpoint work. TLS trust, certificate hostname validity,
RootDSE, search-base discovery, and protocol capability discovery are **not
proven**, because every tested peer reset during the TLS handshake. The exact
needed IT action is to allow this EOAT Atlas API host/network path to complete
a TLS handshake to `gwplastics.com:636`, or identify the required approved
LDAPS access-control/policy path. No certificate exception is requested.

After verified TLS is reachable, IT must supply or approve:

1. the Settings administrator group DN or stable directory identity for
   `EOAT_LDAP_SETTINGS_ADMIN_GROUP`;
2. whether nested group resolution is needed and, if so, an approved narrow
   group search base; and
3. only if direct UPN bind is not supported, the approved narrow user search
   base for anonymous DN discovery (or a separately governed secret mechanism).

User authentication is implemented and unit-tested only; no real-user bind
was attempted. Production activation, production authentication, and all
production writes remain unperformed.
