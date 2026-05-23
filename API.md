# CoachyAI Backend API Reference

Every endpoint below is **implemented** ✅. Use this as the contract between the
React client (Dashboard, Mock Exam, Roadmap, Chat Lesson, Battle, Leaderboard,
Profile) and the FastAPI backend.

- **Base URL (dev):** `http://localhost:8000`
- **API prefix:** `/api/v1`
- **Real-time:** WebSocket at `/ws/battles/{battle_id}`, Server-Sent Events at `/api/v1/chat-lesson/sessions/{id}/messages`
- **Auth:** Bearer JWT in `Authorization` header. Refresh via rotation.
- **OpenAPI:** auto-generated at `/docs` (Swagger) and `/redoc`.

---

## 0. Auth (used by every screen)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register` | Register with phone + password → returns `{access, refresh}` |
| POST | `/api/v1/auth/login` | Login → returns `{access, refresh}` |
| POST | `/api/v1/auth/refresh` | Rotate refresh (old token blacklisted) |
| GET  | `/api/v1/users/me` | Current user profile |
| PATCH| `/api/v1/users/me` | Update profile (language, region, school, target subjects/grade, exam date) |

Frontend pattern: attach `Authorization: Bearer <access>`; on 401 call `/auth/refresh` then retry once.

---

## 1. Dashboard / Home (`/app/home`)

| Method | Path | What it returns |
|---|---|---|
| GET | `/api/v1/progress/dashboard` | One-shot payload: per-subject Rasch, ELO + tier, mastery %, predicted grade, on-track flag, streak |
| GET | `/api/v1/progress/mastery?subject_id=...` | Per-topic mastery (heat map) |
| GET | `/api/v1/progress/snapshots?subject_id=...&weeks=8` | 8-week Rasch trend points (line chart) |
| GET | `/api/v1/progress/predicted-grade?subject_id=...` | Linear extrapolation to exam date with confidence |
| GET | `/api/v1/battles/recent?limit=5` | Last 5 finished battles (avatar, score, W/L, ELO delta) |
| GET | `/api/v1/battles/stats?subject_id=...` | ELO + tier + win streak |
| GET | `/api/v1/leaderboards/me?subject_id=...` | "You're #47 in Math" widget — rank across all scopes |

---

## 2. Mock Exam (`/app/exams`)

### 2.1 Catalog
| Method | Path |
|---|---|
| GET | `/api/v1/subjects` |
| GET | `/api/v1/subjects/{slug}` |
| GET | `/api/v1/subjects/{slug}/topics` |
| GET | `/api/v1/topics/{slug}` |

### 2.2 Start an exam
| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/exams/diagnostic` | `{subject_id, target_grade?}` |
| POST | `/api/v1/exams/full-mock` | `{subject_id}` |
| POST | `/api/v1/exams/checkpoint` | `{topic_id}` |

Each returns the full `AttemptOut` shape with frozen `question_layout`, `started_at`, `expires_at`, and the question list ready to render.

### 2.3 During the exam
| Method | Path | Body | Purpose |
|---|---|---|---|
| GET   | `/api/v1/exam-attempts/{id_or_slug}` | — | Resume / current state |
| POST  | `/api/v1/exam-attempts/{id}/answer` | `{question_index, answer, flagged, time_taken_ms}` | Submit one |
| PATCH | `/api/v1/exam-attempts/{id}/autosave` | `{answers: [...]}` | Bulk save every 30s |
| POST  | `/api/v1/exam-attempts/{id}/submit` | — | Final submit + grade |

### 2.4 Results
| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/exam-attempts/{id}/result` | `{rasch_score, raw_score, grade, correct_count, topic_breakdown, weakest_topics}` |
| GET | `/api/v1/exams/me/recent?limit=20` | Past attempts list |

Grading rules: closed/multi-select/matching by exact compare; open_A by exact-list + accepted_patterns regex; open_B/essay → 0 (LLM-grading async, Phase 2). Rasch score = weighted earned / weighted total × 100. Mastery updated atomically on submit.

---

## 3. Roadmap (`/app/roadmap`)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/v1/roadmap/{subject_slug}` | Auto-generates on first call. Returns `{milestones: [{topic, status, mastery_pct, week_bucket, ...}], weeks_total, on_track}` |
| GET  | `/api/v1/roadmap/{subject_slug}/milestones/{topic_slug}` | Milestone detail: 10 practice question IDs + prereqs + children |
| POST | `/api/v1/roadmap/{subject_slug}/regenerate` | Re-rank after exam result |

Generator: ranks topics by `weight × (1 - mastery_pct)`, respects prerequisite DAG, packs into weekly buckets sized by exam date.

---

## 4. Chat Lesson (`/app/chat-lesson`)

### 4.1 Session CRUD
| Method | Path | Body / Purpose |
|---|---|---|
| POST | `/api/v1/chat-lesson/sessions` | `{topic_id, trigger: "proactive"\|"reactive"}` |
| GET  | `/api/v1/chat-lesson/sessions?limit=20` | Sidebar list |
| GET  | `/api/v1/chat-lesson/sessions/{id_or_slug}` | Session + full message history |
| POST | `/api/v1/chat-lesson/sessions/{id}/end?outcome=ended` | Freeze session |

### 4.2 Streaming a reply (SSE)
**Endpoint:** `POST /api/v1/chat-lesson/sessions/{id}/messages`
**Body:** `{ "content": "Quadratic?" }`
**Returns:** `text/event-stream`

Event types:
- `event: token` · `data: {"content": "..."}`
- `event: math_inline` · `data: {"latex": "x^2"}`
- `event: math_block` · `data: {"latex": "\\int_0^1 f(x)dx"}`
- `event: diagram` · `data: {"mermaid": "graph TD; A-->B"}`
- `event: done` · `data: {"messageId": "...", "tokenCount": 42}`
- `event: error` · `data: {"code": "...", "message": "..."}`

Behind the scenes: a Socratic system prompt feeds the user message + chat history to Gemini (`gemini-2.0-flash-exp` by default). The stream is parsed live for `$...$`, `$$...$$`, and ```mermaid blocks and emitted as structured events. Without `GEMINI_API_KEY` set, a deterministic mock stream is used so the frontend can develop against the protocol.

---

## 5. Battle (`/app/battle`)

### 5.1 Lobby (HTTP)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/battles/stats?subject_id=...` | ELO, tier, next-tier threshold, win streak |
| GET | `/api/v1/battles/recent?limit=10` | Last finished battles |
| GET | `/api/v1/battles/live-count` | `{in_progress: 248}` widget |
| GET | `/api/v1/battles/elo-history?subject_id=...&limit=30` | ELO chart points |

### 5.2 Matchmaking (HTTP → WS)
| Method | Path | Purpose |
|---|---|---|
| POST   | `/api/v1/battles/quick-match` | Body `{subject_id, difficulty_tier?}`. Returns `{status: "SEARCHING"\|"MATCHED", battle_id?, queue_position?, your_elo}`. Server pairs you with any queued player whose ELO is within ±150. |
| GET    | `/api/v1/battles/quick-match/poll?subject_id=...` | Frontend polls this while waiting; flips to MATCHED + battle_id as soon as someone joins. |
| DELETE | `/api/v1/battles/quick-match?subject_id=...` | Leave queue (user pressed Cancel) |
| POST   | `/api/v1/battles/vs-ai` | Body `{subject_id, bot_tier: "BRONZE"\|"SILVER"\|"GOLD"\|"PLATINUM"}` → returns Battle immediately. |

Daily ranked-battle cap (`battle_rate_limit_per_day`, default 30) enforced via Redis counter.

### 5.3 Live duel (WebSocket)
**Endpoint:** `wss://api.coachai.uz/ws/battles/{battle_id_or_slug}?token={access_jwt}`

JWT is in the query string (browsers can't add headers on WS upgrade).

**Server → client frames (JSON):**
```jsonc
// Both connected
{ "type": "battle_ready", "battle_id": "...", "opponent": {"name", "elo", "is_bot"}, "question_count": 10 }
{ "type": "countdown", "seconds_remaining": 3 }
{ "type": "question", "index": 0, "total": 10, "question": {...}, "time_limit_seconds": 30 }
{ "type": "opponent_progress", "current_question": 3, "score": 240 }
{ "type": "question_result", "your_correct": true, "opponent_correct": false, "your_score": 320, "opponent_score": 220, "correct_answer": "C" }
{ "type": "battle_complete", "winner_id": "...", "your_total": 1240, "opponent_total": 980, "elo_delta": 18 }
{ "type": "error", "code": "OPPONENT_DISCONNECTED", "message": "..." }
{ "type": "pong" }   // response to ping
```

**Client → server frames:**
```jsonc
{ "type": "answer", "question_index": 0, "answer": "B", "time_taken_ms": 4250 }
{ "type": "ping" }
{ "type": "forfeit" }
```

Scoring per spec §4.6.2: 100 base + max(0, 30−sec)×2 speed + 20 streak bonus (after 3 correct in a row). Server-authoritative timing. Per-question deadline 30s. After `battle_complete`, ELO is committed to `EloRating`; vs-AI deltas are capped at ±12.

### 5.4 Post-game (HTTP)
| Method | Path |
|---|---|
| GET | `/api/v1/battles/{id_or_slug}` |
| GET | `/api/v1/battles/{id_or_slug}/answers` |

---

## 6. Leaderboards (`/app/leaderboard`)

Four scopes. Each response has `top` (≤100), `me` (your row), and `me_context` (5 above + 5 below).

| Method | Path | Source |
|---|---|---|
| GET | `/api/v1/leaderboards/global?subject_id=...` | Live `EloRating` order |
| GET | `/api/v1/leaderboards/weekly?subject_id=...` | Frozen `LeaderboardEntry` rows (week starts Monday) |
| GET | `/api/v1/leaderboards/regional?subject_id=...` | Filtered by `user.region` (viloyat) |
| GET | `/api/v1/leaderboards/school?subject_id=...` | Filtered by `user.school_id` |
| GET | `/api/v1/leaderboards/me?subject_id=...` | Your rank in all 4 scopes |

---

## 7. Billing / Profile

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/billing/me/plan` | Current plan (Free/Standard/Premium) + `premium_until` + `is_premium_active` |
| GET | `/api/v1/billing/me/grants` | Premium grant history (weekly prize / promo) |

---

## 8. Meta

| Method | Path |
|---|---|
| GET | `/health` |
| GET | `/docs` |
| GET | `/redoc` |
| GET | `/openapi.json` |

---

## Background jobs (Celery beat)

| Task | Schedule (Tashkent) | What it does |
|---|---|---|
| `daily_mastery_snapshot` | every day 00:30 | Writes per-user-per-subject row in `mastery_snapshots` (powers 8-week trend) |
| `grant_weekly_prizes` | Mondays 00:05 | Freezes last week's weekly leaderboard for each subject; grants top-10 a 1-month premium extension |
| `expire_premium_users` | hourly | Downgrades any user whose `premium_until` has passed and has no still-active grant |
| `cleanup_stale_battles` | every 5 min | Marks `READY`/`ACTIVE` battles older than 10 min as `ABANDONED` |

---

## Quick screen → endpoint cheat sheet

| Screen | Endpoints |
|---|---|
| **Dashboard** | `/users/me` · `/progress/dashboard` · `/progress/mastery` · `/progress/snapshots` · `/battles/recent` · `/battles/stats` · `/leaderboards/me` |
| **Mock Exam (start)** | `/subjects` · `/subjects/{slug}/topics` · `/exams/diagnostic` \| `/exams/full-mock` \| `/exams/checkpoint` |
| **Mock Exam (during)** | `/exam-attempts/{id}` · `/exam-attempts/{id}/answer` · `/exam-attempts/{id}/autosave` |
| **Mock Exam (result)** | `/exam-attempts/{id}/submit` · `/exam-attempts/{id}/result` |
| **Roadmap** | `/roadmap/{subject}` · `/roadmap/{subject}/milestones/{id}` · `/roadmap/{subject}/regenerate` |
| **Chat Lesson** | `/chat-lesson/sessions` (CRUD) · **SSE** `/chat-lesson/sessions/{id}/messages` · `/chat-lesson/sessions/{id}/end` |
| **Battle (lobby)** | `/battles/stats` · `/battles/recent` · `/battles/live-count` · `/battles/elo-history` |
| **Battle (start)** | `/battles/quick-match` (POST/GET poll/DELETE) · `/battles/vs-ai` |
| **Battle (live)** | **WS** `/ws/battles/{battle_id}?token=...` |
| **Battle (result)** | `/battles/{id}` · `/battles/{id}/answers` |
| **Leaderboards** | `/leaderboards/global` · `/leaderboards/weekly` · `/leaderboards/regional` · `/leaderboards/school` · `/leaderboards/me` |
| **Profile** | `/users/me` (GET, PATCH) · `/billing/me/plan` · `/billing/me/grants` |
