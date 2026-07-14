# Monitoring and Recovery Results

Result: **PASS**. Compatible staging health was restored in 5.365 seconds after a controlled API stop. Three client caches remained readable; writes were blocked and not queued. Structured API error log lines: 0.

| Endpoint group | Median ms | p95 ms | Max ms |
|---|---:|---:|---:|
| health | 348.928 | 376.822 | 396.331 |
| home | 339.724 | 354.481 | 375.255 |
| search | 372.613 | 395.724 | 403.173 |
| eoat_list | 364.196 | 387.835 | 405.365 |
