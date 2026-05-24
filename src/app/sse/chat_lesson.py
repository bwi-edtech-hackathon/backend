"""Chat lesson SSE endpoint — real Gemini streaming with structured event parsing.

Endpoint: POST /sse/chat-lesson/sessions/{session_id_or_slug}/messages
Returns: text/event-stream

Event types (per spec §6.4 / §8.3):
  - token        {"content": "Let's"}
  - math_inline  {"latex": "x^2"}
  - math_block   {"latex": "\\int_0^1 f(x) dx"}
  - math_pill    {"latex": "x^2 - 5x + 6 = 0"}  // bordered pill formula
  - diagram      {"mermaid": "graph TD; A-->B"}
  - done         {"messageId": "uuid", "tokenCount": int}
  - error        {"code": "...", "message": "..."}

When GEMINI_API_KEY is set, streams from Gemini with a Socratic system prompt
and live-parses LaTeX / mermaid blocks out of the token stream.
When the key is absent, falls back to a deterministic mock stream.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUserId
from app.models.catalog import Subject, Topic
from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from app.models.formula import Formula, FormulaKind
from app.models.progress import MasteryTopic

router = APIRouter(prefix="/api/v1/chat-lesson", tags=["chat-lesson-stream"])


SYSTEM_PROMPT = """You are a patient, knowledgeable Socratic tutor for Uzbekistan's
Milliy Sertifikat exam preparation. Student's language: {language}.

CRITICAL RULES:
1. NEVER lecture. Always ask questions to lead the student to the answer.
2. Take the smallest possible step. If the student is stuck, ask an easier question.
3. Use the student's language ({language}). If they switch, follow them.
4. Render math cleanly: use LaTeX inside $...$ for inline math and $$...$$ for blocks.
   Do not wrap plain variable names in $...$ unless you actually need math typesetting.
5. Use short paragraphs. Avoid Markdown headings. Use **bold** sparingly for key terms.
6. After ~5 successful exchanges, propose a verification problem.
7. End the session when the student demonstrates mastery.

You will receive separate context messages describing the subject, the topic,
the student's mastery, and useful reference formulas BEFORE the actual
conversation history. Treat them as background — do not quote them back at the
student. Reply to the latest student message only.

FORMULA CITATION (REQUIRED):
The "reference formulas" context message lists rows like
    [F-<uuid>] Name — expression
When your reply uses or relies on any of those formulas (even implicitly, e.g.
the student plugs values into one), end your reply with a SINGLE final line:
    [[FORMULAS_USED: F-<uuid>, F-<uuid>]]
Use the EXACT [[FORMULAS_USED: …]] format — no surrounding text, no quotes. If
your reply used none of the listed formulas, omit the tag entirely. Never
invent IDs — only cite IDs that appeared in the context message.

NEVER:
- Give the answer directly
- Praise without verifying understanding
- Switch topics mid-session
- Solve their homework or practice questions verbatim
"""


INLINE_MATH = re.compile(r"\$([^$]+?)\$")
BLOCK_MATH = re.compile(r"\$\$([\s\S]+?)\$\$")
MERMAID_BLOCK = re.compile(r"```mermaid\n([\s\S]+?)```")
# The trailing tag Gemini emits to cite formulas it used. Captured *and
# stripped* from the streamed text before saving / sending to the client.
FORMULAS_USED_TAG = re.compile(
    r"\[\[FORMULAS_USED:\s*([^\]]*)\]\]\s*$",
    re.IGNORECASE,
)
_FORMULA_ID_RE = re.compile(r"F-([0-9a-f\-]{36})", re.IGNORECASE)


def extract_formula_ids(text: str) -> tuple[str, list[str]]:
    """Strip the trailing `[[FORMULAS_USED:...]]` tag from `text` and return
    `(clean_text, [uuid_str, ...])`. If no tag is present, returns the input
    unchanged and an empty list."""
    m = FORMULAS_USED_TAG.search(text)
    if not m:
        return text, []
    ids = _FORMULA_ID_RE.findall(m.group(1) or "")
    clean = text[: m.start()].rstrip()
    return clean, ids


async def _load_context(session_id_or_slug: str, user_id: uuid.UUID):
    async for db in get_db():
        stmt = select(ChatSession)
        try:
            sid = uuid.UUID(session_id_or_slug)
            stmt = stmt.where(ChatSession.id == sid)
        except ValueError:
            stmt = stmt.where(ChatSession.slug == session_id_or_slug)
        sess = (await db.execute(stmt)).scalar_one_or_none()
        if not sess or sess.user_id != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.status != ChatSessionStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="Session is not active")

        subject = (
            await db.execute(select(Subject).where(Subject.id == sess.subject_id))
        ).scalar_one()
        topic = None
        if sess.topic_id:
            topic = (
                await db.execute(select(Topic).where(Topic.id == sess.topic_id))
            ).scalar_one_or_none()

        history = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == sess.id)
                .order_by(ChatMessage.created_at)
            )
        ).scalars().all()

        # Three weakest topics within this subject — gives the tutor a sense of
        # what neighbouring concepts the student is shaky on.
        weak_rows = (
            await db.execute(
                select(MasteryTopic)
                .where(
                    MasteryTopic.user_id == user_id,
                    MasteryTopic.subject_id == sess.subject_id,
                )
                .order_by(MasteryTopic.mastery_pct.asc())
                .limit(3)
            )
        ).scalars().all()
        weak_topic_names: list[str] = []
        for row in weak_rows:
            t = (
                await db.execute(select(Topic).where(Topic.id == row.topic_id))
            ).scalar_one_or_none()
            if t:
                weak_topic_names.append(f"{t.name_en} ({float(row.mastery_pct):.0f}%)")

        formulas = await _load_formulas(db, sess.subject_id, topic)
        return sess, subject, topic, list(history), weak_topic_names, formulas
    raise HTTPException(status_code=500, detail="DB unavailable")


async def _load_formulas(db, subject_id: uuid.UUID, topic: Topic | None) -> list[Formula]:
    """Pull the formula candidates Gemini may cite for this session.

    Strategy: every FORMULA-kind row for the subject is fair game (the right
    rail surfaces them all too), with topic-linked / keyword-matching rows
    prioritized first so the most relevant rows aren't dropped if we ever
    have to truncate. Reference-kind rows (humanities link lists) are
    excluded — they're not citation candidates in chat."""
    rows = (
        await db.execute(
            select(Formula)
            .where(
                Formula.subject_id == subject_id,
                Formula.kind == FormulaKind.FORMULA,
            )
            .order_by(Formula.group_title, Formula.order_index)
        )
    ).scalars().all()
    if not topic:
        return list(rows)
    topic_name_lc = (topic.name_en or "").lower()

    def _is_relevant(f: Formula) -> bool:
        if f.topic_id == topic.id:
            return True
        for kw in f.keywords or []:
            if isinstance(kw, str) and kw.lower() in topic_name_lc:
                return True
        return False

    relevant = [f for f in rows if _is_relevant(f)]
    rest = [f for f in rows if f not in relevant]
    return relevant + rest


def _build_context_turns(
    subject: Subject,
    topic: Topic | None,
    mastery_pct: float,
    weak_topics: list[str],
    formulas: list[Formula] | None = None,
) -> list[dict]:
    """Split situational context into discrete user→model turns prepended to the
    Gemini chat history. Each turn covers ONE aspect (subject, topic, mastery,
    formulas) so the model can attend to them independently."""
    turns: list[dict] = []

    def _pair(question: str, answer: str) -> None:
        turns.append({"role": "user", "parts": [question]})
        turns.append({"role": "model", "parts": [answer]})

    # 1. Subject framing.
    _pair(
        "What exam and subject is this tutoring session for?",
        (
            f"This is for Uzbekistan's Milliy Sertifikat ({subject.name_en}). "
            "Stay within this subject; do not drift into other subjects."
        ),
    )

    # 2. Topic framing.
    topic_label = topic.name_en if topic else "general review"
    _pair(
        "What specific topic is the student working on right now?",
        (
            f"The active topic is: {topic_label}. "
            "All questions, examples, and hints should stay anchored to this topic."
        ),
    )

    # 3. Mastery snapshot + weak neighbours.
    if weak_topics:
        weak_str = "; ".join(weak_topics)
        _pair(
            "How well does the student know this material so far?",
            (
                f"Current mastery estimate on this topic: {mastery_pct:.0f}%. "
                f"Weakest related topics (with % mastery): {weak_str}. "
                "Calibrate question difficulty to this level — do not assume mastery they have not shown."
            ),
        )
    else:
        _pair(
            "How well does the student know this material so far?",
            (
                f"Current mastery estimate on this topic: {mastery_pct:.0f}%. "
                "No prior performance data on neighbouring topics — start with a gentle diagnostic question."
            ),
        )

    # 4. Reference formulas pulled from the DB. Each row carries a stable
    # `F-<uuid>` ID; cite the IDs of the formulas the model actually uses via
    # the trailing [[FORMULAS_USED:…]] tag (see SYSTEM_PROMPT).
    if formulas:
        lines = ["Reference formulas for this session (cite the ones you use):"]
        for f in formulas:
            display = f.latex if f.latex else f.expression
            lines.append(f"  [F-{f.id}] {f.name} — {display}")
        lines.append(
            "After your reply, list the IDs you relied on with:\n"
            "    [[FORMULAS_USED: F-<uuid>, F-<uuid>]]\n"
            "Omit the tag if you used none. Do not invent IDs."
        )
        _pair(
            "What canonical formulas or facts should I keep handy for this topic?",
            "\n".join(lines),
        )

    return turns


async def _save_message(
    session_id: uuid.UUID,
    role: ChatMessageRole,
    content: str,
    parts: list,
    token_count: int,
    formula_ids: list[str] | None = None,
) -> uuid.UUID:
    async for db in get_db():
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            parts=parts,
            token_count=token_count,
            formula_ids=list(formula_ids or []),
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg.id
    return uuid.uuid4()


def _parse_structured(buf: str) -> tuple[list[tuple[str, dict]], str]:
    """Extract complete math/mermaid blocks from buffer. Return (events, remainder)."""
    events: list[tuple[str, dict]] = []
    remainder = buf

    # Block math first (greedy)
    while True:
        m = BLOCK_MATH.search(remainder)
        if not m:
            break
        if m.start() > 0:
            events.append(("token", {"content": remainder[: m.start()]}))
        events.append(("math_block", {"latex": m.group(1).strip()}))
        remainder = remainder[m.end() :]

    # Mermaid diagrams
    while True:
        m = MERMAID_BLOCK.search(remainder)
        if not m:
            break
        if m.start() > 0:
            events.append(("token", {"content": remainder[: m.start()]}))
        events.append(("diagram", {"mermaid": m.group(1).strip()}))
        remainder = remainder[m.end() :]

    # Inline math
    while True:
        m = INLINE_MATH.search(remainder)
        if not m:
            break
        if m.start() > 0:
            events.append(("token", {"content": remainder[: m.start()]}))
        events.append(("math_inline", {"latex": m.group(1).strip()}))
        remainder = remainder[m.end() :]

    return events, remainder


async def _gemini_stream(
    prompt: str,
    system: str,
    history: list[ChatMessage],
    context_turns: list[dict],
) -> AsyncIterator[str]:
    """Yield raw text chunks from Gemini.

    The conversation sent to Gemini is composed of three slices in order:
      1. `context_turns` — synthetic user→model pairs holding the situational
         briefing (subject, topic, mastery, formulas). Each piece of context
         lives in its own turn so the model can attend to them independently.
      2. `history` — the real prior ChatMessages from this session.
      3. `prompt` — the current student message (sent via send_message).
    """
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=system,
    )
    chat_history: list[dict] = list(context_turns)
    for m in history:
        role = "user" if m.role == ChatMessageRole.USER else "model"
        chat_history.append({"role": role, "parts": [m.content]})

    chat = model.start_chat(history=chat_history)
    response = await asyncio.to_thread(chat.send_message, prompt, stream=True)
    for chunk in response:
        text = getattr(chunk, "text", "") or ""
        if text:
            yield text


async def _stub_stream() -> AsyncIterator[str]:
    parts = [
        "Let's take a look — what type of equation is ",
        "$x^2 - 5x + 6 = 0$",
        "? Take a moment and ",
        "tell me the form you recognise.",
    ]
    for p in parts:
        await asyncio.sleep(0.15)
        yield p


@router.post("/sessions/{session_id_or_slug}/messages")
async def stream_message(
    session_id_or_slug: str,
    user_id: CurrentUserId,
    payload: dict = Body(...),
) -> EventSourceResponse:
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")

    sess, subject, topic, history, weak_topics, formulas = await _load_context(
        session_id_or_slug, user_id
    )

    # Persist the user message immediately
    await _save_message(
        sess.id, ChatMessageRole.USER, content, parts=[], token_count=len(content.split())
    )

    system_prompt = SYSTEM_PROMPT.format(
        language={"uz": "Uzbek", "ru": "Russian", "en": "English"}.get("en", "Uzbek"),
    )
    context_turns = _build_context_turns(
        subject=subject,
        topic=topic,
        mastery_pct=float(sess.mastery_estimate),
        weak_topics=weak_topics,
        formulas=formulas,
    )

    async def _generator() -> AsyncIterator[dict]:
        full_text = ""
        emitted_parts: list[dict] = []
        buffer = ""
        token_count = 0

        try:
            if settings.gemini_enabled:
                text_iter = _gemini_stream(
                    content, system_prompt, history, context_turns
                )
            else:
                text_iter = _stub_stream()

            async for chunk in text_iter:
                full_text += chunk
                buffer += chunk
                events, remainder = _parse_structured(buffer)
                if events:
                    for evt, data in events:
                        emitted_parts.append({"type": evt, **data})
                        token_count += len(str(data).split())
                        yield {"event": evt, "data": json.dumps(data)}
                    buffer = remainder
                else:
                    # Flush any safe (non-dollar, non-backtick, non-`[` so the
                    # trailing `[[FORMULAS_USED:...]]` tag is held back) prefix.
                    safe_idx = len(buffer)
                    for i, ch in enumerate(buffer):
                        if ch in "$`[":
                            safe_idx = i
                            break
                    if safe_idx > 0:
                        text = buffer[:safe_idx]
                        emitted_parts.append({"type": "token", "content": text})
                        token_count += len(text.split())
                        yield {"event": "token", "data": json.dumps({"content": text})}
                        buffer = buffer[safe_idx:]

            # Strip the trailing citation tag (from both the buffered remainder
            # and the accumulated full_text) before flushing the final token.
            buffer, tail_ids = extract_formula_ids(buffer)
            full_text, full_ids = extract_formula_ids(full_text)
            cited_ids = tail_ids or full_ids

            if buffer.strip():
                emitted_parts.append({"type": "token", "content": buffer})
                token_count += len(buffer.split())
                yield {"event": "token", "data": json.dumps({"content": buffer})}

            if cited_ids:
                yield {
                    "event": "formulas_used",
                    "data": json.dumps({"ids": cited_ids}),
                }

            msg_id = await _save_message(
                sess.id,
                ChatMessageRole.COACH,
                full_text,
                emitted_parts,
                token_count,
                formula_ids=cited_ids,
            )

            yield {
                "event": "done",
                "data": json.dumps(
                    {"messageId": str(msg_id), "tokenCount": token_count}
                ),
            }
        except Exception as e:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps({"code": "STREAM_ERROR", "message": str(e)}),
            }

    return EventSourceResponse(_generator())
