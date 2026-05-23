# CoachAI Backend

FastAPI backend for **CoachAI** — an AI-powered BMBA Milliy Sertifikat (Uzbekistan National Certificate) exam prep platform.

> Tagline: **"BMBA prep, rebuilt with AI."**

## Features (MVP scope)

- **Auth** — phone + password, JWT access/refresh
- **Catalog** — 8 subjects (Math, Phys, Chem, Bio, Hist, Geog, Uzb-lit, Rus-lit) × 3 langs (uz/ru/en)
- **Mock exams** — diagnostic (30 min adaptive) + full mock (150 min, 55 sub-answers), closed + open-A grading, auto-save every 30s
- **Personal progress** — difficulty-weighted mastery, daily snapshots, predicted grade
- **Roadmap** — rule-based topic sequencing
- **Chat lesson** — Gemini SSE streaming Socratic tutor, math (KaTeX) + diagrams
- **Battle** — Quick Match (WebSocket) + vs AI bot (4 tiers: Bronze/Silver/Gold/Platinum), per-subject ELO
- **Leaderboards** — Global, Weekly, Regional, School (4 scopes)
- **Billing** — weekly prize Celery beat (top 10 weekly → Premium month)

## Stack

| Layer | Tech |
|---|---|
| Runtime | Python 3.12 |
| Framework | FastAPI + uvicorn |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic |
| Database | Postgres 16 |
| Cache / queues | Redis 7 |
| Background | Celery + Celery beat |
| LLM | Google Gemini (`gemini-2.0-flash-exp`) |
| Real-time | WebSocket (battles) + SSE (chat lesson) |
| Auth | PyJWT (HS256) + passlib bcrypt |

## Project layout

```
backend/
├── src/app/
│   ├── main.py                # FastAPI entry
│   ├── core/                  # config, db, redis, security, deps, exceptions, slugs
│   ├── models/                # SQLAlchemy ORM
│   ├── modules/               # business logic per domain
│   │   ├── iam/               # auth, users
│   │   ├── catalog/           # subjects, topics
│   │   ├── exams/             # diagnostic, full mock, checkpoints
│   │   ├── progress/          # mastery, snapshots, predicted grade
│   │   ├── roadmap/           # rule-based plan
│   │   ├── chat_lesson/       # Gemini SSE tutor
│   │   ├── battle/            # WS battles + AI bot + ELO
│   │   ├── leaderboards/      # 4 scopes
│   │   └── billing/           # weekly prize
│   ├── ws/                    # WebSocket endpoints
│   ├── sse/                   # SSE endpoints
│   └── workers/               # Celery app + tasks
├── alembic/                   # migrations
├── scripts/                   # seed scripts
├── tests/                     # pytest
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## Quickstart (local dev)

```bash
# 1. Clone + setup env
cp .env.example .env
# Edit .env — set GEMINI_API_KEY (or leave blank for stubbed responses)

# 2. Start infra (postgres + redis)
docker compose up -d postgres redis

# 3. Install deps
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 4. Run migrations
alembic upgrade head

# 5. Seed catalog (8 subjects in 3 languages)
python scripts/seed_subjects.py

# 6. Run API
uvicorn app.main:app --reload --app-dir src

# 7. Verify
curl http://localhost:8000/health
# → {"status":"ok","app":"coachai-backend","env":"local"}

# 8. Run tests
pytest
```

## Quickstart (full Docker)

```bash
cp .env.example .env
docker compose up --build
# API on http://localhost:8000
# Celery worker + beat run as separate containers
```

## API surface (high-level)

| Module | Base path | Real-time |
|---|---|---|
| Auth | `/api/v1/auth/*` | — |
| Users | `/api/v1/users/*` | — |
| Catalog | `/api/v1/subjects`, `/api/v1/topics` | — |
| Exams | `/api/v1/exams/*`, `/api/v1/exam-attempts/*` | — |
| Progress | `/api/v1/progress/*` | — |
| Roadmap | `/api/v1/roadmap/*` | — |
| Chat lesson | `/api/v1/chat-lesson/*` | `POST /api/v1/chat-lesson/sessions/{id}/messages` → **SSE** |
| Battle | `/api/v1/battles/*` | `wss://.../ws/battles/{battle_id}?token=...` |
| Leaderboards | `/api/v1/leaderboards/*` | — |

Full OpenAPI: `http://localhost:8000/docs`

## Configuration

All config via env vars (Pydantic Settings). See `.env.example`.

Notable:
- `GEMINI_API_KEY` — leave blank during dev → chat lesson returns stub stream
- `CORS_ORIGINS=*` — fine for hackathon; tighten in prod
- `BATTLE_RATE_LIMIT_PER_DAY=30` — per spec anti-cheat

## Scope decisions (locked)

| Concern | Decision |
|---|---|
| Friendship system | **Dropped** for MVP (Friends leaderboard also dropped — 4 scopes ship) |
| Question types graded | Closed + Open-A (regex/fuzzy). Open-B and essay → Phase 2 |
| Mastery model | Difficulty-weighted % correct (not full Rasch/IRT) |
| Rasch trend | Daily snapshots via Celery beat, linear extrapolation for predicted grade |
| Content sourcing | Official BMBA samples (where available) + Gemini-generated, all 3 langs |
| OTP / verification | Skipped — password only |
| Payments | Skipped for MVP — weekly prize grants Premium via Celery only |

## Phasing

This scaffold = **Batch 1**: project structure, infra, auth working, all other modules stubbed.

Upcoming batches:
- **B2**: Catalog (subjects/topics CRUD, slugs)
- **B3**: Exams (diagnostic + full mock + grading)
- **B4**: Progress + Roadmap (mastery, snapshots, predicted grade)
- **B5**: Battle (WebSocket, AI bot, ELO, matchmaking)
- **B6**: Chat lesson (Gemini SSE)
- **B7**: Leaderboards (4 scopes, Redis ZSETs)
- **B8**: Celery beat (snapshots, weekly prize, leaderboard reset)

## License

Proprietary — bwi-edtech-hackathon.
