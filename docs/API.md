# Gbẹdu — API Reference

Base URL: `https://api.gbedu.com` (production) / `http://localhost:8000` (local)

All endpoints are versioned under `/api/v1/`. All request and response bodies are JSON. Timestamps are ISO 8601 UTC strings.

---

## Authentication

### Token model

Gbẹdu uses JWT bearer tokens. Access tokens expire in 30 minutes. Refresh tokens expire in 30 days (sliding window — refreshed on each use).

Include the access token in every authenticated request:

```
Authorization: Bearer <access_token>
```

### Rate limits

| Tier | Requests/minute | Generations/day |
|------|----------------|----------------|
| Anonymous | 20 | 0 |
| Free | 60 | 3 |
| Creator | 300 | 25 |
| Pro | 1 000 | 100 |
| Label | 5 000 | unlimited |

Rate limit headers returned on every response:
```
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 247
X-RateLimit-Reset: 1718400000
```

On limit exceeded: `429 Too Many Requests` with `Retry-After` header.

---

## Error format

All errors follow this shape:

```json
{
  "error": {
    "code": "TRACK_NOT_FOUND",
    "message": "Track abc123 does not exist or you do not have access to it.",
    "details": {}
  }
}
```

### Error codes

| HTTP | Code | Meaning |
|------|------|---------|
| 400 | `VALIDATION_ERROR` | Request body failed schema validation |
| 401 | `NOT_AUTHENTICATED` | Missing or invalid Authorization header |
| 401 | `TOKEN_EXPIRED` | Access token has expired — refresh it |
| 403 | `FORBIDDEN` | Authenticated but insufficient permissions |
| 403 | `INSUFFICIENT_CREDITS` | User has 0 credits remaining |
| 404 | `TRACK_NOT_FOUND` | Track does not exist or not accessible |
| 404 | `GENERATION_NOT_FOUND` | Generation ID not found |
| 404 | `USER_NOT_FOUND` | User not found |
| 404 | `VOICE_MODEL_NOT_FOUND` | Voice model not found |
| 409 | `EMAIL_ALREADY_EXISTS` | Registration attempt with existing email |
| 409 | `GENERATION_ALREADY_COMPLETED` | Cannot cancel a completed generation |
| 422 | `VALIDATION_ERROR` | Semantic validation failed (e.g. BPM out of range) |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 502 | `ML_UNAVAILABLE` | ML service unreachable — try again |
| 503 | `SERVICE_UNAVAILABLE` | Scheduled maintenance or overload |

---

## Health endpoints

These are unauthenticated and used by load balancers and Kubernetes probes.

### GET /health

Returns 200 if the service process is running. Does not check downstream dependencies.

Response `200`:
```json
{
  "status": "ok",
  "service": "gbedu-api",
  "version": "0.1.0"
}
```

### GET /ready

Returns 200 only if the service can serve traffic (DB connection pool healthy, Redis reachable).

Response `200`:
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

Response `503` (not ready):
```json
{
  "status": "not_ready",
  "checks": {
    "database": "ok",
    "redis": "error: connection refused"
  }
}
```

---

## Auth endpoints

### POST /api/v1/auth/register

Register a new user with email + password.

Request:
```json
{
  "email": "artist@example.com",
  "password": "correct-horse-battery",
  "display_name": "Tunde Beats"
}
```

Response `201`:
```json
{
  "user": {
    "id": "01906d28-abcd-7000-8000-abc123def456",
    "email": "artist@example.com",
    "display_name": "Tunde Beats",
    "subscription_tier": "free",
    "credits_remaining": 10,
    "created_at": "2024-06-14T02:00:00Z"
  },
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

Errors: `400 VALIDATION_ERROR`, `409 EMAIL_ALREADY_EXISTS`

---

### POST /api/v1/auth/login

Authenticate with email + password.

Request:
```json
{
  "email": "artist@example.com",
  "password": "correct-horse-battery"
}
```

Response `200`:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": { "id": "...", "email": "...", "display_name": "..." }
}
```

Errors: `401 NOT_AUTHENTICATED` (wrong password or unknown email)

---

### POST /api/v1/auth/refresh

Exchange a refresh token for a new access token. The old refresh token is invalidated.

Request:
```json
{
  "refresh_token": "eyJ..."
}
```

Response `200`:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

Errors: `401 TOKEN_EXPIRED`, `401 NOT_AUTHENTICATED`

---

### POST /api/v1/auth/logout

Invalidate the refresh token (blacklist in Redis).

Request:
```json
{
  "refresh_token": "eyJ..."
}
```

Response `204`: no body.

---

### GET /api/v1/auth/google

Initiate Google OAuth2 flow. Redirects to Google consent screen.

Query params:
- `redirect_uri` (required) — where Google redirects after consent

Response `302`: redirect to Google.

---

### GET /api/v1/auth/google/callback

OAuth2 callback. Handled server-side; redirects to frontend with tokens in URL fragment.

Response `302`: redirects to `{FRONTEND_URL}/auth/callback#access_token=...&refresh_token=...`

---

## User endpoints

All require authentication.

### GET /api/v1/users/me

Return the authenticated user's profile.

Response `200`:
```json
{
  "id": "01906d28-...",
  "email": "artist@example.com",
  "display_name": "Tunde Beats",
  "avatar_url": "https://cdn.gbedu.com/avatars/01906d28.jpg",
  "subscription_tier": "creator",
  "credits_remaining": 18,
  "created_at": "2024-06-14T02:00:00Z"
}
```

---

### PATCH /api/v1/users/me

Update display name or avatar.

Request (all fields optional):
```json
{
  "display_name": "Tunde Official",
  "avatar_url": "https://..."
}
```

Response `200`: updated user object (same shape as GET /users/me).

---

## Track endpoints

### GET /api/v1/tracks

List the authenticated user's tracks. Supports pagination.

Query params:
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)
- `is_public` (bool, optional filter)

Response `200`:
```json
{
  "items": [
    {
      "id": "01906d28-...",
      "title": "Lagos Nights",
      "genre": "afrobeats",
      "bpm": 128,
      "key": "A minor",
      "mood": "euphoric",
      "duration_ms": 210000,
      "mp3_url": "https://cdn.gbedu.com/...",
      "cover_url": null,
      "is_public": true,
      "play_count": 142,
      "created_at": "2024-06-14T02:00:00Z"
    }
  ],
  "total": 47,
  "page": 1,
  "page_size": 20
}
```

---

### GET /api/v1/tracks/{track_id}

Fetch a single track. Public tracks are accessible without authentication.

Response `200`: single track object (same shape as items above, plus `wav_url` if user owns it).

Errors: `404 TRACK_NOT_FOUND`, `403 FORBIDDEN`

---

### PATCH /api/v1/tracks/{track_id}

Update track metadata. Owner only.

Request (all optional):
```json
{
  "title": "Lagos Nights (Remix)",
  "description": "Afrobeats fusion with Amapiano elements",
  "is_public": true,
  "is_marketplace_listed": true,
  "price_usd": "2.99"
}
```

Response `200`: updated track object.

---

### DELETE /api/v1/tracks/{track_id}

Soft-delete a track. Owner only. Sets `deleted_at`, removes from marketplace.

Response `204`: no body.

---

## Generation endpoints

### POST /api/v1/generations

Request a new AI music generation. Deducts 1 credit from the user's balance.

Request:
```json
{
  "genre": "afrobeats",
  "bpm": 128,
  "key": "A minor",
  "mood": "euphoric",
  "instruments": ["drums", "talking_drum", "bass", "guitar", "synth"],
  "lyrics_prompt": "a song about late nights in Lagos, celebrating life",
  "voice_model_id": null,
  "duration_seconds": 180,
  "title": "Lagos Nights"
}
```

Field constraints:
- `genre`: one of `afrobeats`, `afropop`, `amapiano`, `highlife`, `afro-fusion`, `afro-trap`
- `bpm`: integer 60–200
- `key`: note + mode, e.g. `"A minor"`, `"C# major"`
- `mood`: one of `euphoric`, `melancholic`, `energetic`, `romantic`, `spiritual`, `rebellious`
- `instruments`: 1–8 items from the instrument catalog
- `lyrics_prompt`: max 500 characters; omit for instrumental
- `duration_seconds`: 30–300
- `title`: max 200 characters; auto-generated if omitted

Response `202`:
```json
{
  "generation_id": "01906d30-...",
  "status": "pending",
  "estimated_seconds": 120,
  "credits_remaining": 17
}
```

Errors: `403 INSUFFICIENT_CREDITS`, `422 VALIDATION_ERROR`, `502 ML_UNAVAILABLE`

---

### GET /api/v1/generations/{generation_id}

Poll generation status. Poll every 3–5 seconds; do not poll faster.

Response `200` (pending/processing):
```json
{
  "generation_id": "01906d30-...",
  "status": "processing",
  "progress": {
    "step": "music",
    "percent": 45
  },
  "estimated_seconds_remaining": 65
}
```

Response `200` (completed):
```json
{
  "generation_id": "01906d30-...",
  "status": "completed",
  "track": {
    "id": "01906d31-...",
    "title": "Lagos Nights",
    "mp3_url": "https://cdn.gbedu.com/...",
    "wav_url": "https://cdn.gbedu.com/...",
    "duration_ms": 180000,
    "bpm": 128,
    "key": "A minor"
  }
}
```

Response `200` (failed):
```json
{
  "generation_id": "01906d30-...",
  "status": "failed",
  "error": "ML service timeout after 600s"
}
```

Note: credits are refunded automatically on failure.

---

### GET /api/v1/generations

List the authenticated user's generation history.

Query params: `page`, `page_size`, `status` (filter by status)

Response `200`:
```json
{
  "items": [
    {
      "generation_id": "01906d30-...",
      "status": "completed",
      "title": "Lagos Nights",
      "genre": "afrobeats",
      "created_at": "2024-06-14T02:00:00Z",
      "completed_at": "2024-06-14T02:02:14Z"
    }
  ],
  "total": 12,
  "page": 1,
  "page_size": 20
}
```

---

### DELETE /api/v1/generations/{generation_id}

Cancel a pending generation and refund the credit. Cannot cancel a generation that is already processing or completed.

Response `204`: no body.

Errors: `409 GENERATION_ALREADY_COMPLETED`

---

## Voice model endpoints

### GET /api/v1/voice-models

List available voice models (system-provided + user's own).

Response `200`:
```json
{
  "items": [
    {
      "id": "01906d00-...",
      "name": "Afrobeats Male Vocal",
      "description": "Generic Afrobeats-trained male voice model",
      "sample_audio_url": "https://cdn.gbedu.com/samples/male-vocal.mp3",
      "is_public": true,
      "owner_id": null
    }
  ]
}
```

---

### POST /api/v1/voice-models

Upload a custom voice model. Creator tier and above only.

Request: `multipart/form-data`
- `name` (string, required)
- `description` (string, optional)
- `sample_audio` (file, required, 10–30 seconds of clean vocal audio, WAV or MP3, max 50MB)

Response `201`:
```json
{
  "id": "01906d40-...",
  "name": "My Custom Voice",
  "status": "processing",
  "message": "Voice model training queued. Ready in approximately 30 minutes."
}
```

---

## Marketplace endpoints

### GET /api/v1/marketplace

Browse publicly listed tracks for sale.

Query params:
- `genre` (filter)
- `mood` (filter)
- `min_bpm`, `max_bpm` (filter)
- `sort` (`popular`, `recent`, `price_asc`, `price_desc`)
- `page`, `page_size`

Response `200`:
```json
{
  "items": [
    {
      "track_id": "01906d31-...",
      "title": "Lagos Nights",
      "artist": "Tunde Beats",
      "genre": "afrobeats",
      "bpm": 128,
      "duration_ms": 180000,
      "price_usd": "2.99",
      "preview_url": "https://cdn.gbedu.com/.../preview_30s.mp3",
      "play_count": 1402,
      "cover_url": null
    }
  ],
  "total": 238,
  "page": 1,
  "page_size": 20
}
```

---

### POST /api/v1/marketplace/purchase

Purchase a marketplace track.

Request:
```json
{
  "track_id": "01906d31-...",
  "license_type": "commercial",
  "payment_method_id": "pm_stripe_abc123"
}
```

`license_type`: `personal` or `commercial`

Response `200`:
```json
{
  "purchase_id": "01906d50-...",
  "track_id": "01906d31-...",
  "mp3_url": "https://cdn.gbedu.com/...",
  "wav_url": "https://cdn.gbedu.com/...",
  "license_type": "commercial",
  "receipt_url": "https://invoice.stripe.com/..."
}
```

Errors: `402 PAYMENT_REQUIRED` (payment failed), `409` (already purchased)

---

## Payment endpoints

### GET /api/v1/payments/plans

List available subscription plans.

Response `200`:
```json
{
  "plans": [
    {
      "tier": "creator",
      "name": "Creator",
      "price_usd_monthly": "9.99",
      "price_ngn_monthly": "14999",
      "generations_per_day": 25,
      "features": ["wav downloads", "custom voice models", "marketplace selling"]
    },
    {
      "tier": "pro",
      "name": "Pro",
      "price_usd_monthly": "29.99",
      "price_ngn_monthly": "44999",
      "generations_per_day": 100,
      "features": ["everything in Creator", "stem separation", "priority queue"]
    }
  ]
}
```

---

### POST /api/v1/payments/subscribe

Subscribe to a plan via Stripe (international) or Paystack (Nigeria/Africa).

Request:
```json
{
  "tier": "creator",
  "provider": "stripe",
  "payment_method_id": "pm_abc123"
}
```

Response `200`:
```json
{
  "subscription_id": "sub_stripe_abc123",
  "status": "active",
  "current_period_end": "2024-07-14T02:00:00Z",
  "tier": "creator"
}
```

---

### POST /api/v1/payments/credits

Purchase additional generation credits.

Request:
```json
{
  "credits": 50,
  "provider": "paystack",
  "payment_reference": "paystack_ref_abc123"
}
```

Response `200`:
```json
{
  "credits_purchased": 50,
  "credits_remaining": 67,
  "amount_charged_ngn": "2499"
}
```

---

### POST /api/v1/payments/webhook/stripe

Stripe webhook endpoint. Signature verified via `Stripe-Signature` header. Do not call directly.

### POST /api/v1/payments/webhook/paystack

Paystack webhook endpoint. Signature verified via `x-paystack-signature` header. Do not call directly.

---

## Instrument catalog

Valid values for the `instruments` array in generation requests:

| Category | Values |
|----------|--------|
| Percussion | `drums`, `talking_drum`, `shekere`, `conga`, `djembe`, `agogo`, `claps` |
| Bass | `bass`, `bass_synth` |
| Harmony | `guitar`, `piano`, `organ`, `synth`, `pad` |
| Lead | `lead_synth`, `flute`, `saxophone`, `trumpet` |
| Texture | `strings`, `choir`, `fx` |

---

## Supported genres

`afrobeats`, `afropop`, `amapiano`, `highlife`, `afro-fusion`, `afro-trap`

---

## Pagination

All list endpoints use cursor-free page-based pagination:

```
GET /api/v1/tracks?page=2&page_size=20
```

Response always includes `total`, `page`, `page_size`. To iterate all pages:
```
while page * page_size < total: fetch next page
```
