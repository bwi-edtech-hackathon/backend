"""Seed schools, users, ELO ratings, finished battles, leaderboard entries,
mastery topics + 8-week snapshots, exam attempts, and a couple of chat sessions.

Reads existing subjects + questions — must run AFTER scripts/seed_subjects.py
and scripts/seed_content.py. Idempotent: re-running won't duplicate.

Run with:
    python scripts/seed_users.py
"""

from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.slugs import short_slug, slugify  # noqa: E402
from app.models.battle import (  # noqa: E402
    Battle,
    BattleAnswer,
    BattleMode,
    BattleStatus,
    BotTier,
    EloRating,
)
from app.models.catalog import Question, Subject, SubjectCode  # noqa: E402
from app.models.chat import (  # noqa: E402
    ChatMessage,
    ChatMessageRole,
    ChatSession,
    ChatSessionStatus,
    ChatTrigger,
)
from app.models.exam import (  # noqa: E402
    ExamAttempt,
    ExamKind,
    ExamStatus,
    Grade,
)
from app.models.leaderboard import (  # noqa: E402
    LeaderboardEntry,
    LeaderboardScope,
    School,
)
from app.models.progress import (  # noqa: E402
    MasterySnapshot,
    MasteryTopic,
)
from app.models.user import Plan, User, UserLanguage  # noqa: E402


DEMO_USER_PHONE = "+998900000000"


# ─────────────────────────────────────────────────────────────────────────────
# Reference data
# ─────────────────────────────────────────────────────────────────────────────

SCHOOLS = [
    ("Lyceum #1, Tashkent", "Tashkent", "Tashkent"),
    ("Westminster IUT", "Tashkent", "Tashkent"),
    ("Presidential School", "Tashkent", "Tashkent"),
    ("School #243", "Tashkent", "Tashkent"),
    ("IB Tashkent", "Tashkent", "Tashkent"),
    ("Lyceum #2", "Tashkent", "Tashkent"),
    ("School #19", "Tashkent", "Tashkent"),
    ("Lyceum #1, Samarkand", "Samarkand", "Samarkand"),
    ("School #11, Bukhara", "Bukhara", "Bukhara"),
    ("Andijan State Lyceum", "Andijan", "Andijan"),
    ("Ferghana Lyceum #4", "Ferghana", "Ferghana"),
    ("Khorezm Mamun Academy", "Khorezm", "Urgench"),
]


UZBEK_NAMES = [
    ("Aziz", "Karimov", "M"), ("Lola", "Rashidova", "F"), ("Otabek", "Saidov", "M"),
    ("Nodira", "Abdullayeva", "F"), ("Jamshid", "Tursunov", "M"), ("Madina", "Nazarova", "F"),
    ("Sardor", "Akhmedov", "M"), ("Dilshoda", "Mansurova", "F"), ("Bekzod", "Yusupov", "M"),
    ("Sevara", "Mirzayeva", "F"), ("Doniyor", "Tukhtayev", "M"), ("Gulnoza", "Salimova", "F"),
    ("Asad", "Rakhimov", "M"), ("Munisa", "Khasanova", "F"), ("Ruslan", "Ibragimov", "M"),
    ("Aziza", "Komilova", "F"), ("Sherzod", "Olimov", "M"), ("Javokhir", "Karimov", "M"),
    ("Nigora", "Kamilova", "F"), ("Ulug'bek", "Mirzayev", "M"), ("Kamola", "Yusupova", "F"),
    ("Botir", "Pulatov", "M"), ("Iroda", "Saidova", "F"), ("Ravshan", "Murodov", "M"),
    ("Zilola", "Tashkentova", "F"), ("Bahodir", "Ergashev", "M"), ("Shahnoza", "Akbarova", "F"),
    ("Jasur", "Ergashev", "M"), ("Feruza", "Niyozova", "F"), ("Anvar", "Khalilov", "M"),
    ("Malika", "Yo'ldosheva", "F"), ("Akmal", "Saidkhonov", "M"), ("Dilnoza", "Yusupova", "F"),
    ("Sanjar", "Komilov", "M"), ("Mavluda", "Karimova", "F"), ("Farrukh", "Rakhimov", "M"),
    ("Zarina", "Nazirova", "F"), ("Komron", "Saidov", "M"), ("Husan", "Davlatov", "M"),
    ("Shaxnoza", "Boboeva", "F"), ("Hasan", "Mamadaliyev", "M"), ("Hilola", "Yo'ldosheva", "F"),
    ("Akrom", "Mirsadiqov", "M"), ("Rano", "Salimova", "F"), ("Behzod", "Tursunov", "M"),
    ("Charos", "Madaminova", "F"), ("Daler", "Komilov", "M"), ("Mahliyo", "Saidova", "F"),
]


REGIONS = ["Tashkent", "Samarkand", "Bukhara", "Andijan", "Ferghana", "Khorezm"]


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency helpers
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_schools(db) -> list[School]:
    existing = (await db.execute(select(School))).scalars().all()
    by_name = {s.name: s for s in existing}
    created = []
    for name, region, city in SCHOOLS:
        if name in by_name:
            created.append(by_name[name])
            continue
        s = School(name=name, region=region, city=city)
        db.add(s)
        created.append(s)
    await db.commit()
    for s in created:
        if not s.id:
            await db.refresh(s)
    return (await db.execute(select(School))).scalars().all()


async def ensure_demo_user(db, schools: list[School]) -> User:
    res = await db.execute(select(User).where(User.phone == DEMO_USER_PHONE))
    u = res.scalar_one_or_none()
    if u:
        return u
    u = User(
        phone=DEMO_USER_PHONE,
        full_name="Diana M.",
        password_hash=hash_password("demo-mode-no-login"),
        language=UserLanguage.EN,
        region="Tashkent",
        school_id=schools[0].id,
        plan=Plan.FREE,
        streak_days=12,
        last_active_date=date.today(),
        target_grade="B+",
        exam_target_date=date.today() + timedelta(days=120),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def patch_demo_user(db, user: User, schools: list[School]) -> None:
    """Backfill demo profile fields if missing (already-created demo user)."""
    changed = False
    if not user.region:
        user.region = "Tashkent"
        changed = True
    if not user.school_id:
        user.school_id = schools[0].id
        changed = True
    if user.streak_days < 1:
        user.streak_days = 12
        changed = True
    if not user.target_grade:
        user.target_grade = "B+"
        changed = True
    if not user.exam_target_date:
        user.exam_target_date = date.today() + timedelta(days=120)
        changed = True
    if not user.last_active_date:
        user.last_active_date = date.today()
        changed = True
    if changed:
        await db.commit()


async def ensure_users(db, schools: list[School], demo: User, rng: random.Random) -> list[User]:
    """Create ~48 students. Idempotent on phone."""
    out = [demo]
    for i, (first, last, _gender) in enumerate(UZBEK_NAMES):
        phone = f"+99899{(1000000 + i):07d}"
        res = await db.execute(select(User).where(User.phone == phone))
        u = res.scalar_one_or_none()
        if u:
            out.append(u)
            continue
        school = rng.choice(schools)
        u = User(
            phone=phone,
            full_name=f"{first} {last}",
            password_hash=hash_password("demo-seed"),
            language=rng.choice([UserLanguage.UZ, UserLanguage.RU, UserLanguage.EN]),
            region=school.region,
            school_id=school.id,
            plan=rng.choices(
                [Plan.FREE, Plan.STANDARD, Plan.PREMIUM], weights=[7, 2, 1]
            )[0],
            streak_days=rng.randint(0, 30),
            last_active_date=date.today() - timedelta(days=rng.randint(0, 5)),
            target_grade=rng.choice(["B", "B+", "A", "A+"]),
            exam_target_date=date.today() + timedelta(days=rng.randint(60, 200)),
        )
        db.add(u)
        out.append(u)
    await db.commit()
    return out


async def ensure_elo(db, users: list[User], subjects: list[Subject], rng: random.Random) -> None:
    """Each non-demo user gets ELO in ~4 random subjects; demo gets all 8."""
    existing = {
        (e.user_id, e.subject_id): e
        for e in (await db.execute(select(EloRating))).scalars().all()
    }
    demo = users[0]
    # Demo: all 8 subjects with believable distribution
    demo_subject_ratings = {
        SubjectCode.MATH: 1487,
        SubjectCode.PHYS: 1410,
        SubjectCode.CHEM: 1335,
        SubjectCode.BIO: 1290,
        SubjectCode.HIST: 1380,
        SubjectCode.GEOG: 1320,
        SubjectCode.UZB_LIT: 1450,
        SubjectCode.RUS_LIT: 1402,
    }
    for s in subjects:
        rating = demo_subject_ratings.get(s.code, 1400)
        battles = rng.randint(12, 35)
        wins = rng.randint(7, 22)
        losses = rng.randint(5, 14)
        draws = rng.randint(0, 3)
        existing_row = existing.get((demo.id, s.id))
        if existing_row:
            # Refresh demo's row so frontend shows live values
            existing_row.rating = rating
            existing_row.battles_count = battles
            existing_row.wins = wins
            existing_row.losses = losses
            existing_row.draws = draws
            existing_row.current_streak = rng.randint(0, 4)
            existing_row.best_streak = rng.randint(4, 9)
            existing_row.is_provisional = False
            continue
        db.add(EloRating(
            user_id=demo.id,
            subject_id=s.id,
            rating=rating,
            battles_count=battles,
            wins=wins,
            losses=losses,
            draws=draws,
            current_streak=rng.randint(0, 4),
            best_streak=rng.randint(4, 9),
            is_provisional=False,
        ))

    for u in users[1:]:
        chosen = rng.sample(subjects, k=rng.randint(3, 6))
        for s in chosen:
            if (u.id, s.id) in existing:
                continue
            # Generate a plausible rating distribution
            base = rng.choices(
                [950, 1100, 1250, 1400, 1550, 1700, 1850, 2000, 2150],
                weights=[2, 4, 7, 9, 9, 7, 5, 3, 2],
            )[0]
            rating = base + rng.randint(-80, 80)
            battles = rng.randint(5, 60)
            wins = int(battles * rng.uniform(0.35, 0.65))
            losses = battles - wins - rng.randint(0, 2)
            losses = max(losses, 0)
            db.add(EloRating(
                user_id=u.id,
                subject_id=s.id,
                rating=rating,
                battles_count=battles,
                wins=wins,
                losses=losses,
                draws=max(0, battles - wins - losses),
                current_streak=rng.randint(0, 6),
                best_streak=rng.randint(3, 12),
                is_provisional=battles < 10,
            ))
    await db.commit()


async def ensure_battles(
    db,
    users: list[User],
    subjects: list[Subject],
    rng: random.Random,
) -> None:
    """Seed ~120 finished battles. Most involve the demo user so battle history
    is populated; remainder are between other users for liveliness."""
    demo = users[0]
    # Count existing seeded battles (those whose slug starts with "seed-")
    pre_count = (
        await db.execute(
            select(func.count(Battle.id)).where(Battle.slug.like("seed-%"))
        )
    ).scalar_one()
    if pre_count and pre_count > 0:
        print(f"⏭  battles already seeded ({pre_count}) — skipping")
        return

    # Cache questions per subject for layout building
    subj_questions: dict[uuid.UUID, list[Question]] = {}
    for s in subjects:
        rows = (
            await db.execute(
                select(Question)
                .where(
                    Question.subject_id == s.id,
                    Question.suitable_for_battle.is_(True),
                )
                .limit(50)
            )
        ).scalars().all()
        subj_questions[s.id] = rows

    bot_names = [
        "Aziza", "Sherzod", "Madina", "Bekzod", "Nigora", "Javokhir",
        "Dilshoda", "Otabek", "Munisa", "Ruslan", "Gulnoza", "Asad",
    ]

    BATTLE_COUNT = 120
    now = datetime.now(UTC)
    for i in range(BATTLE_COUNT):
        subj = rng.choice(subjects)
        questions = subj_questions.get(subj.id, [])
        if len(questions) < 10:
            continue
        chosen_qs = rng.sample(questions, 10)
        layout = [
            {
                "index": j,
                "question_id": str(q.id),
                "topic_id": str(q.topic_id),
                "points": float(q.points),
                "difficulty": float(q.difficulty),
            }
            for j, q in enumerate(chosen_qs)
        ]

        # 70% of battles include the demo as player A; 20% other-vs-other; 10% demo-vs-AI
        kind = rng.choices(["demo_vs_ai", "demo_vs_human", "other_vs_other"],
                           weights=[3, 7, 2])[0]
        if kind == "other_vs_other":
            player_a, player_b = rng.sample(users[1:], 2)
            bot_tier = None
            bot_name = None
            mode = BattleMode.QUICK_MATCH
        elif kind == "demo_vs_ai":
            player_a, player_b = demo, None
            bot_tier = rng.choice([BotTier.BRONZE, BotTier.SILVER, BotTier.GOLD, BotTier.PLATINUM])
            bot_name = f"AI · {bot_tier.value.title()} bot"
            mode = BattleMode.VS_AI
        else:
            player_a = demo
            player_b = rng.choice(users[1:])
            bot_tier = None
            bot_name = None
            mode = BattleMode.QUICK_MATCH

        # ELOs at start: pull current or default 1400
        a_elo = await _get_rating(db, player_a.id, subj.id, default=1400)
        if player_b:
            b_elo = await _get_rating(db, player_b.id, subj.id, default=1400)
        else:
            b_elo = {BotTier.BRONZE: 1000, BotTier.SILVER: 1300,
                     BotTier.GOLD: 1600, BotTier.PLATINUM: 1900}[bot_tier]

        # Generate score (per question: 100 base + speed bonus)
        a_correct = rng.randint(4, 10)
        b_correct = rng.randint(3, 10)
        a_score = a_correct * 100 + rng.randint(0, a_correct * 35)
        b_score = b_correct * 100 + rng.randint(0, b_correct * 35)
        if a_score > b_score:
            winner = player_a.id
            delta_a = rng.randint(8, 22)
        elif a_score < b_score:
            winner = player_b.id if player_b else None
            delta_a = -rng.randint(6, 14)
        else:
            winner = None
            delta_a = 0
        delta_b = -delta_a

        finished_at = now - timedelta(
            days=rng.randint(0, 28), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        started_at = finished_at - timedelta(minutes=rng.randint(3, 12))

        battle = Battle(
            slug=f"seed-{i:03d}-{short_slug(subj.code.value)}",
            subject_id=subj.id,
            mode=mode,
            status=BattleStatus.FINISHED,
            player_a_id=player_a.id,
            player_b_id=player_b.id if player_b else None,
            bot_tier=bot_tier,
            bot_name=bot_name or (rng.choice(bot_names) if player_b else None),
            rating_a_start=a_elo,
            rating_b_start=b_elo,
            question_layout=layout,
            question_count=10,
            started_at=started_at,
            finished_at=finished_at,
            score_a=a_score,
            score_b=b_score,
            correct_a=a_correct,
            correct_b=b_correct,
            time_a_ms=rng.randint(45_000, 290_000),
            time_b_ms=rng.randint(45_000, 290_000),
            winner_id=winner,
            elo_delta_a=delta_a,
            elo_delta_b=delta_b,
        )
        db.add(battle)
        await db.flush()

        # Synthetic per-question answers (one row per side per question)
        for j, q in enumerate(chosen_qs):
            correct_letter = q.correct_answer if isinstance(q.correct_answer, str) else "A"
            for side, score_total, correct_total in (
                ("a", a_score, a_correct),
                ("b", b_score, b_correct),
            ):
                is_correct = rng.random() < (correct_total / 10)
                letter = correct_letter if is_correct else rng.choice(
                    [l for l in ("A", "B", "C", "D") if l != correct_letter]
                )
                user_id = player_a.id if side == "a" else (player_b.id if player_b else None)
                speed = rng.randint(0, 50)
                base = 100 if is_correct else 0
                db.add(BattleAnswer(
                    battle_id=battle.id,
                    user_id=user_id,
                    question_id=q.id,
                    question_index=j,
                    answer=letter,
                    is_correct=is_correct,
                    time_taken_ms=rng.randint(2_500, 9_500),
                    base_points=base,
                    speed_bonus=speed if is_correct else 0,
                    streak_bonus=0,
                    total_points=base + (speed if is_correct else 0),
                ))

    # Sprinkle a few live (READY/ACTIVE) battles for the Battle.tsx "live" tab
    LIVE = 3
    for i in range(LIVE):
        subj = rng.choice(subjects)
        questions = subj_questions.get(subj.id, [])
        if len(questions) < 10:
            continue
        chosen_qs = rng.sample(questions, 10)
        layout = [
            {
                "index": j,
                "question_id": str(q.id),
                "topic_id": str(q.topic_id),
                "points": float(q.points),
                "difficulty": float(q.difficulty),
            }
            for j, q in enumerate(chosen_qs)
        ]
        player_a, player_b = rng.sample(users[1:], 2)
        db.add(Battle(
            slug=f"seed-live-{i:02d}-{short_slug(subj.code.value)}",
            subject_id=subj.id,
            mode=BattleMode.QUICK_MATCH,
            status=BattleStatus.ACTIVE,
            player_a_id=player_a.id,
            player_b_id=player_b.id,
            rating_a_start=1400 + rng.randint(-200, 400),
            rating_b_start=1400 + rng.randint(-200, 400),
            question_layout=layout,
            question_count=10,
            started_at=now - timedelta(minutes=rng.randint(1, 6)),
            bot_name=f"{player_b.full_name.split()[0]}",
        ))

    await db.commit()


async def _get_rating(db, user_id: uuid.UUID, subject_id: uuid.UUID, default: int) -> int:
    row = (
        await db.execute(
            select(EloRating).where(
                EloRating.user_id == user_id, EloRating.subject_id == subject_id
            )
        )
    ).scalar_one_or_none()
    return row.rating if row else default


async def ensure_leaderboard_weekly(db, users: list[User], subjects: list[Subject]) -> None:
    """Build weekly leaderboard entries (current Monday-based week) using ELO order."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    # Drop existing entries for this period (idempotent reseed)
    existing = (
        await db.execute(
            select(LeaderboardEntry).where(
                LeaderboardEntry.scope == LeaderboardScope.WEEKLY,
                LeaderboardEntry.period_start == monday,
            )
        )
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.commit()

    for subj in subjects:
        rows = (
            await db.execute(
                select(EloRating, User)
                .join(User, User.id == EloRating.user_id)
                .where(EloRating.subject_id == subj.id, User.is_active.is_(True))
                .order_by(EloRating.rating.desc())
                .limit(100)
            )
        ).all()
        for rank, (elo, u) in enumerate(rows, start=1):
            db.add(LeaderboardEntry(
                scope=LeaderboardScope.WEEKLY,
                subject_id=subj.id,
                user_id=u.id,
                period_start=monday,
                period_end=sunday,
                region=u.region,
                school_id=u.school_id,
                score=elo.rating,
                rank=rank,
                wins=elo.wins,
                losses=elo.losses,
                streak=elo.current_streak,
            ))
    await db.commit()


async def ensure_demo_progress(db, demo: User, subjects: list[Subject], rng: random.Random) -> None:
    """Populate demo's MasteryTopic + 8 weeks of MasterySnapshot for each subject."""
    # MasteryTopic — one per topic of each subject
    from app.models.catalog import Topic

    for subj in subjects:
        topics = (
            await db.execute(
                select(Topic).where(Topic.subject_id == subj.id, Topic.depth == 2)
            )
        ).scalars().all()
        for t in topics:
            existing = (
                await db.execute(
                    select(MasteryTopic).where(
                        MasteryTopic.user_id == demo.id,
                        MasteryTopic.topic_id == t.id,
                    )
                )
            ).scalar_one_or_none()
            mastery = Decimal(str(round(rng.uniform(20, 95), 2)))
            attempts = rng.randint(4, 24)
            correct = int(attempts * float(mastery) / 100)
            if existing:
                # Replace placeholder rows (mastery 0% but seeded by other code paths)
                if float(existing.mastery_pct) < 5:
                    existing.mastery_pct = mastery
                    existing.attempts_count = attempts
                    existing.correct_count = correct
                    existing.weighted_earned = Decimal(str(round(correct * 2.2, 2)))
                    existing.weighted_total = Decimal(str(round(attempts * 2.2, 2)))
                    existing.last_attempted_at = datetime.now(UTC) - timedelta(days=rng.randint(0, 10))
                continue
            db.add(MasteryTopic(
                user_id=demo.id,
                topic_id=t.id,
                subject_id=subj.id,
                mastery_pct=mastery,
                attempts_count=attempts,
                correct_count=correct,
                weighted_earned=Decimal(str(round(correct * 2.2, 2))),
                weighted_total=Decimal(str(round(attempts * 2.2, 2))),
                last_attempted_at=datetime.now(UTC) - timedelta(days=rng.randint(0, 10)),
            ))

        # 8 weekly snapshots, growing trend
        baseline = 35 + rng.uniform(0, 20)
        slope = rng.uniform(0.4, 1.3)
        for w in range(8):
            snap_date = date.today() - timedelta(weeks=7 - w)
            existing = (
                await db.execute(
                    select(MasterySnapshot).where(
                        MasterySnapshot.user_id == demo.id,
                        MasterySnapshot.subject_id == subj.id,
                        MasterySnapshot.snapshot_date == snap_date,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue
            rasch = round(min(100.0, baseline + slope * w + rng.uniform(-1.5, 1.5)), 2)
            elo = 1300 + int((rasch - 40) * 4)
            db.add(MasterySnapshot(
                user_id=demo.id,
                subject_id=subj.id,
                snapshot_date=snap_date,
                rasch_score=Decimal(str(rasch)),
                grade=_grade_for(rasch),
                topic_mastery={},
                elo=elo,
            ))
    await db.commit()


def _grade_for(score: float) -> str:
    if score >= 70: return "A+"
    if score >= 65: return "A"
    if score >= 60: return "B+"
    if score >= 55: return "B"
    if score >= 50: return "C+"
    if score >= 46: return "C"
    return "F"


async def ensure_demo_exam_history(db, demo: User, subjects: list[Subject], rng: random.Random) -> None:
    math = next((s for s in subjects if s.code == SubjectCode.MATH), None)
    if not math:
        return
    existing = (
        await db.execute(
            select(func.count(ExamAttempt.id)).where(ExamAttempt.user_id == demo.id)
        )
    ).scalar_one()
    if existing >= 3:
        return
    now = datetime.now(UTC)
    for i, (offset_days, score) in enumerate([(14, 51.2), (7, 54.1), (2, 58.2)]):
        attempt = ExamAttempt(
            slug=short_slug(f"demo-mock-{i}"),
            user_id=demo.id,
            template_id=None,
            subject_id=math.id,
            kind=ExamKind.FULL_MOCK,
            status=ExamStatus.GRADED,
            question_layout=[],
            started_at=now - timedelta(days=offset_days, hours=2),
            submitted_at=now - timedelta(days=offset_days, hours=-1),
            graded_at=now - timedelta(days=offset_days, hours=-2),
            raw_score=Decimal(str(score)),
            rasch_score=Decimal(str(score)),
            grade=Grade.B if score >= 55 else Grade.C_PLUS,
            topic_breakdown={},
            weakest_topics=[],
        )
        db.add(attempt)
    await db.commit()


async def ensure_demo_chat(db, demo: User, subjects: list[Subject]) -> None:
    math = next((s for s in subjects if s.code == SubjectCode.MATH), None)
    if not math:
        return
    existing = (
        await db.execute(
            select(func.count(ChatSession.id)).where(ChatSession.user_id == demo.id)
        )
    ).scalar_one()
    if existing > 0:
        return
    now = datetime.now(UTC)
    session = ChatSession(
        slug=short_slug("demo-quad"),
        user_id=demo.id,
        subject_id=math.id,
        topic_id=None,
        trigger=ChatTrigger.PROACTIVE,
        status=ChatSessionStatus.ACTIVE,
        mastery_at_start=Decimal("48.00"),
        mastery_estimate=Decimal("62.00"),
        started_at=now - timedelta(hours=2),
    )
    db.add(session)
    await db.flush()
    db.add_all([
        ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.SYSTEM,
            content="Tutoring session for Quadratic equations",
        ),
        ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.COACH,
            content=("Hey Diana — let's look at x² − 5x + 6 = 0. What's the discriminant formula?"),
        ),
        ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.USER,
            content="D = b² − 4ac",
        ),
        ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.COACH,
            content="Perfect. Now plug in a = 1, b = −5, c = 6.",
        ),
    ])
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def seed() -> None:
    rng = random.Random(20260524)
    async with async_session_factory() as db:
        subjects = (
            await db.execute(select(Subject).order_by(Subject.order_index))
        ).scalars().all()
        if not subjects:
            print("⚠  Subjects table is empty. Run scripts/seed_subjects.py first.")
            return

        # Check that battle questions exist
        q_count = (
            await db.execute(
                select(func.count(Question.id)).where(Question.suitable_for_battle.is_(True))
            )
        ).scalar_one()
        if q_count < 10:
            print(
                f"⚠  only {q_count} battle-suitable questions — "
                "run scripts/seed_content.py first."
            )
            return

        schools = await ensure_schools(db)
        demo = await ensure_demo_user(db, schools)
        await patch_demo_user(db, demo, schools)
        users = await ensure_users(db, schools, demo, rng)
        print(f"✅ users: {len(users)} (demo + {len(users) - 1} students)")

        await ensure_elo(db, users, subjects, rng)
        elo_count = (await db.execute(select(func.count(EloRating.id)))).scalar_one()
        print(f"✅ elo_ratings: {elo_count}")

        await ensure_battles(db, users, subjects, rng)
        battle_count = (
            await db.execute(select(func.count(Battle.id)).where(Battle.slug.like("seed-%")))
        ).scalar_one()
        print(f"✅ battles (seed-*): {battle_count}")

        await ensure_leaderboard_weekly(db, users, subjects)
        lb_count = (
            await db.execute(select(func.count(LeaderboardEntry.id)))
        ).scalar_one()
        print(f"✅ leaderboard_entries (weekly): {lb_count}")

        await ensure_demo_progress(db, demo, subjects, rng)
        mt = (await db.execute(select(func.count(MasteryTopic.id)))).scalar_one()
        ms = (await db.execute(select(func.count(MasterySnapshot.id)))).scalar_one()
        print(f"✅ demo mastery_topics: {mt} | mastery_snapshots: {ms}")

        await ensure_demo_exam_history(db, demo, subjects, rng)
        ea = (await db.execute(select(func.count(ExamAttempt.id)))).scalar_one()
        print(f"✅ exam_attempts: {ea}")

        await ensure_demo_chat(db, demo, subjects)
        cs = (await db.execute(select(func.count(ChatSession.id)))).scalar_one()
        print(f"✅ chat_sessions: {cs}")


if __name__ == "__main__":
    asyncio.run(seed())
