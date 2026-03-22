# Strava API Reference

Base URL: `https://www.strava.com/api/v3`
Auth: `Authorization: Bearer <access_token>`

## Key Endpoints

### Activities
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/athlete/activities` | GET | List athlete activities |
| `/activities/{id}` | GET | Get detailed activity |

### /athlete/activities params
- `before` — epoch timestamp, activities before this time
- `after`  — epoch timestamp, activities after this time
- `page`   — page number (default 1)
- `per_page` — results per page (default 30, max 200)

---

## Activity Object — Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Activity ID |
| `name` | string | Activity name |
| `type` | string | e.g. "Ride", "VirtualRide", "Run" |
| `start_date_local` | datetime | Local start time |
| `distance` | float | Meters |
| `moving_time` | int | Seconds |
| `elapsed_time` | int | Seconds |
| `total_elevation_gain` | float | Meters |
| `average_speed` | float | m/s |
| `max_speed` | float | m/s |
| `average_watts` | float | Average power (requires power meter) |
| `max_watts` | int | Max power |
| `weighted_average_watts` | int | Normalized power |
| `average_heartrate` | float | Average HR (requires HR monitor) |
| `max_heartrate` | float | Max HR |
| `calories` | float | Estimated calories |
| `suffer_score` | int | Strava relative effort score |
| `segment_efforts` | array | Segment efforts with PR ranks |
| `kudos_count` | int | Kudos received |
| `map.summary_polyline` | string | Encoded route polyline |

---

## OAuth Flow

**Auth URL:**
```
https://www.strava.com/oauth/authorize
  ?client_id=YOUR_CLIENT_ID
  &response_type=code
  &redirect_uri=http://localhost/exchange_token
  &approval_prompt=force
  &scope=read,activity:read_all
```

**Token Exchange:**
```
POST https://www.strava.com/oauth/token
  client_id, client_secret, code, grant_type=authorization_code
```

**Token Refresh:**
```
POST https://www.strava.com/oauth/token
  client_id, client_secret, refresh_token, grant_type=refresh_token
```

Token response includes `access_token`, `refresh_token`, `expires_at` (epoch).

---

## Rate Limits
- 100 requests / 15 min
- 1,000 requests / day

The `strava_api.py` helper handles token refresh automatically.

---

## Local Cache

Activities are cached at `~/.cache/strava/activities.json` via `strava_cache.py`.

**Strategy:** on each call to `get_activities()`, only activities newer than the most recent cached entry are fetched from the API (using the `after` param). New results are merged into the cache and deduplicated by `id`. Filtering by `days`, `limit`, and `activity_type` is then applied to the full local cache.

| File | Purpose |
|------|---------|
| `~/.cache/strava/activities.json` | Cached activity list (newest-first) |
| `~/.cache/strava/last_sync.txt` | ISO timestamp of last successful sync |

**Cache functions (`strava_cache.py`):**
- `load_cached_activities()` — returns full cached list
- `update_cache_with_new_activities(new)` — merges, deduplicates, sorts, saves
- `get_activity_by_id(id)` — lookup without an API call
- `get_last_sync_time()` — returns last sync timestamp string

**Fields not available in list endpoint** (require `GET /activities/{id}`):
- `segment_efforts` — PR ranks, KOM ranks
- `splits_metric` / `laps`
- Full description
