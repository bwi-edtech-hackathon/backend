"""Battle WebSocket — STUB for B1; full implementation in Batch 5.

Endpoint: wss://api.coachai.uz/ws/battles/{battle_id}?token=<jwt>

Protocol (per spec §6.3):

Server → Client events:
  - battle_ready       {opponent: {name, avatar, elo}, question_count}
  - countdown          {seconds_remaining}
  - question           {index, total, question, time_limit_seconds}
  - opponent_progress  {current_question, score}     (no answer revealed)
  - question_result    {your_correct, opponent_correct, your_score, opponent_score}
  - battle_complete    {winner_id, your_total, opponent_total, elo_delta}
  - error              {code, message}

Client → Server events:
  - answer    {question_index, answer, time_taken_ms}
  - ping      (heartbeat, every 10s)
  - forfeit
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.security import decode_token

router = APIRouter()


@router.websocket("/ws/battles/{battle_id}")
async def battle_ws(
    websocket: WebSocket,
    battle_id: str,
    token: str = Query(...),
) -> None:
    """Battle live channel (STUB).

    Auth: JWT in query param (per spec §6.3). Heartbeat: 10s ping.
    """
    # 1. Verify JWT before accepting
    try:
        payload = decode_token(token, expected_type="access")
        user_id = payload["sub"]
    except (jwt.InvalidTokenError, KeyError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid_token")
        return

    await websocket.accept()
    await websocket.send_json({
        "type": "error",
        "code": "NOT_IMPLEMENTED",
        "message": "Battle WS handler ships in Batch 5",
        "battle_id": battle_id,
        "user_id": user_id,
    })

    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "code": "NOT_IMPLEMENTED",
                    "message": f"echo: {msg}",
                })
    except WebSocketDisconnect:
        return
