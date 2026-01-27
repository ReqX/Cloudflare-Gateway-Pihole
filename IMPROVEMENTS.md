# Improvement Plan

## Adlist Download Resilience: Cache Fallback

### Problem
External adlist sources (e.g., `https://big.oisd.nl/domainswild2`) can be temporarily unavailable or close connections prematurely. This causes the entire workflow to fail, leaving Gateway rules without updates.

**Current behavior:**
- Download fails → workflow fails → no updates applied

### Proposed Solution: Cache with Fallback

**Flow:**
```
1. Try download fresh adlist
2. If success → save to cache file, use fresh data
3. If fail → use cached version (if exists), log warning
4. If fail + no cache → fail hard
```

### Implementation

1. **Add cache files to repo:**
   - `lists/adlist_cache.txt` - last successful blocklist download
   - `lists/whitelist_cache.txt` - last successful whitelist download

2. **Modify `DomainConverter.process_urls()` in `src/domains.py`:**
   - Wrap each `download_file()` call in try/except
   - On success: write to cache file
   - on failure: read from cache file if exists, log warning about stale data
   - If no cache: re-raise exception

3. **Initial cache:** Commit baseline empty cache files or fetch once during dev

### Trade-offs

| Pro | Con |
|-----|-----|
| Workflow continues even if source is down | Cache may get stale if source is down for days |
| Always have *some* protection rather than none | Requires commits to update cache |
| Simple implementation | Cache files in repo add noise to git history |

### Alternatives Considered

| Option | Description | Why Not Chosen |
|--------|-------------|----------------|
| Increase retries only | Give more attempts before failing | Still fails if server is persistently down |
| Skip failed adlists | Continue with remaining sources | Loses valuable blocklist coverage |
| GitHub Actions cache/store | Use actions/cache or artifacts | Adds complexity, cache expires |
| Mirror/fallback sources | Use alternate URLs for redundancy | Hard to find reliable mirrors |

### Priority
**Medium** - Current retry logic helps with transient issues, but persistent outages still cause total failure. This would add resilience.
