# Cloudflare Gateway-Pihole

Syncs Pi-hole adlists to Cloudflare Gateway Zero Trust.

## Retry & Error Handling

The codebase implements a custom retry system in `src/requests.py` with differentiated handling for different error types:

### HTTP Error Categories

| Error Type | Status Codes | Retry Behavior | Total Retry Window |
|------------|--------------|----------------|-------------------|
| **Server-side** (5xx) | 500-599 | 15 retries with exponential backoff | ~5.5 minutes |
| **Rate limit** (429) | 429 | Unlimited retries, 2 min initial delay | Continues until success |
| **Client errors** (4xx) | 400, 403, 404 | 5 retries with exponential backoff | ~31 seconds |
| **Network errors** | Timeout, connection failures | 5 retries with exponential backoff | ~31 seconds |

### Exception Hierarchy

```
HTTPException
├── RateLimitException  # 429 - never stops retrying
└── ServerSideException # 5xx - 15 retries before failure
```

### Key Functions

- `cloudflare_gateway_request()` - Core API wrapper with 30s timeout
- `@retry(**retry_config)` - Decorator applying retry logic to Cloudflare API calls
- `@rate_limited_request` - Decorator enforcing 1 req/s rate limiting

### Important Notes

- `update_list()` in `src/cloudflare.py` has internal retry logic for "item not found in list" errors (400s from removing already-removed domains)
- Network timeouts (30s) are separate from retry backoff - failed requests count as one retry attempt
- Exponential backoff uses `max_wait=30` seconds for server-side errors

## Workflow

GitHub Actions runs `python -m src run` daily at 02:00 UTC via `.github/workflows/main.yml`.
