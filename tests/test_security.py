"""Unit tests for password hashing + JWT issuance."""

from __future__ import annotations

import uuid

import jwt
import pytest

from app.core.security import (
    decode_token,
    hash_password,
    issue_token,
    issue_token_pair,
    verify_password,
)


def test_password_roundtrip() -> None:
    hashed = hash_password("Sup3rSecret!")
    assert hashed != "Sup3rSecret!"
    assert verify_password("Sup3rSecret!", hashed)
    assert not verify_password("wrong", hashed)


def test_issue_and_decode_access() -> None:
    uid = uuid.uuid4()
    token = issue_token(uid, "access")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(uid)
    assert payload["type"] == "access"


def test_decode_wrong_type_rejected() -> None:
    uid = uuid.uuid4()
    refresh = issue_token(uid, "refresh")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, expected_type="access")


def test_token_pair_shape() -> None:
    uid = uuid.uuid4()
    pair = issue_token_pair(uid)
    assert {"access_token", "refresh_token", "token_type", "expires_in"} <= set(pair)
    assert pair["token_type"] == "Bearer"
    assert pair["expires_in"] > 0
