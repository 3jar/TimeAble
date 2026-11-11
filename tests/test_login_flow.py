"""Tests for the OTP suspend/resume login registry.

`run(ask)` 콜러블로 로그인 흐름을 흉내낸다 — 네트워크 없음. start()/submit_otp()가
다음 status까지 블록하므로 스레드 동기화가 결정적이다.
"""
import pytest

from timeable.gls.login_flow import (
    DONE,
    ERROR,
    OTP_REQUESTED,
    AttemptNotFound,
    LoginRegistry,
)


def test_no_otp_completes_immediately():
    reg = LoginRegistry()
    attempt_id, (status, payload) = reg.start(lambda ask: {"ok": True})
    assert status == DONE
    assert payload == {"ok": True}
    assert reg.active_count() == 0  # 완료되면 폐기


def test_single_otp_roundtrip():
    reg = LoginRegistry()
    received = []

    def run(ask):
        code = ask("otp?")
        received.append(code)
        return {"code": code}

    attempt_id, first = reg.start(run)
    assert first == (OTP_REQUESTED, None)
    assert reg.active_count() == 1

    status, payload = reg.submit_otp(attempt_id, "1234")
    assert status == DONE
    assert payload == {"code": "1234"}
    assert received == ["1234"]
    assert reg.active_count() == 0


def test_otp_retry_asks_again():
    reg = LoginRegistry()
    seen = []

    def run(ask):
        first = ask("otp?")
        seen.append(first)
        if first != "0000":           # 첫 코드가 틀렸다고 치고 재요청
            second = ask("again?")
            seen.append(second)
            return {"final": second}
        return {"final": first}

    attempt_id, status = reg.start(run)
    assert status[0] == OTP_REQUESTED

    status = reg.submit_otp(attempt_id, "9999")   # 틀린 코드 -> 재요청
    assert status[0] == OTP_REQUESTED

    status = reg.submit_otp(attempt_id, "1234")   # 두번째 코드 -> 완료
    assert status == (DONE, {"final": "1234"})
    assert seen == ["9999", "1234"]


def test_error_is_surfaced():
    reg = LoginRegistry()

    def run(ask):
        raise ValueError("bad password")

    _, (status, payload) = reg.start(run)
    assert status == ERROR
    assert isinstance(payload, ValueError)
    assert str(payload) == "bad password"
    assert reg.active_count() == 0


def test_error_after_otp():
    reg = LoginRegistry()

    def run(ask):
        ask("otp?")
        raise RuntimeError("gls schema changed")

    attempt_id, first = reg.start(run)
    assert first[0] == OTP_REQUESTED
    status, payload = reg.submit_otp(attempt_id, "1234")
    assert status == ERROR
    assert isinstance(payload, RuntimeError)


def test_unknown_attempt_raises():
    reg = LoginRegistry()
    with pytest.raises(AttemptNotFound):
        reg.submit_otp("nope", "1234")


def test_submit_after_done_raises():
    reg = LoginRegistry()
    attempt_id, _ = reg.start(lambda ask: "done")
    with pytest.raises(AttemptNotFound):
        reg.submit_otp(attempt_id, "1234")


def test_cleanup_expires_stale_attempts():
    reg = LoginRegistry(ttl_seconds=-1)  # 즉시 만료

    def run(ask):
        ask("otp?")  # OTP 대기하며 멈춤
        return "x"

    attempt_id, first = reg.start(run)   # OTP_REQUESTED 상태로 대기
    assert first[0] == OTP_REQUESTED
    reg.cleanup()                        # TTL 음수 -> 만료
    assert reg.active_count() == 0
    with pytest.raises(AttemptNotFound):
        reg.submit_otp(attempt_id, "1234")


def test_cancel_abandons_attempt():
    reg = LoginRegistry()

    def run(ask):
        ask("otp?")
        return "x"

    attempt_id, _ = reg.start(run)
    reg.cancel(attempt_id)
    assert reg.active_count() == 0
    with pytest.raises(AttemptNotFound):
        reg.submit_otp(attempt_id, "1234")
