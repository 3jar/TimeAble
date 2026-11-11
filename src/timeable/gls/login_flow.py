"""진행중 로그인 오케스트레이션 — 웹 OTP suspend/resume.

로그인은 워커 스레드에서 돌고, OTP가 필요하면 **다른 HTTP 요청**으로 들어오는
코드를 기다리며 멈춘다. 이 레지스트리가 둘을 잇는다: 로그인 스레드는 `ask()`로
멈추고(suspend), 웹 계층은 `submit_otp()`로 코드를 넣어 재개(resume)한다.

GLS/네트워크와 **분리**돼 있다 — `start()`는 임의의 `run(ask) -> result` 콜러블을
받으므로, 실제 로그인 없이 단위 테스트할 수 있다. (`run`은 보통 GLS 로그인+import)

흐름::

    attempt_id, status = registry.start(run)      # OTP_REQUESTED | DONE | ERROR
    status = registry.submit_otp(attempt_id, code) # OTP_REQUESTED | DONE | ERROR
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

OTP_REQUESTED = "OTP_REQUESTED"
DONE = "DONE"
ERROR = "ERROR"


class OtpCancelled(Exception):
    """attempt가 취소/만료되어 로그인 스레드를 깨울 때 내부적으로 발생."""


class AttemptNotFound(KeyError):
    """없는/만료된 attempt_id."""


@dataclass
class _Attempt:
    otp_in: queue.Queue      # 웹 -> 스레드: OTP 코드
    status_out: queue.Queue  # 스레드 -> 웹: (status, payload)
    thread: threading.Thread
    created_at: float
    meta: dict


class LoginRegistry:
    """attempt_id로 식별되는 진행중 로그인들의 인메모리 레지스트리.

    단일 상주 프로세스(Render) 전제. `ttl_seconds` 지나면 만료 청소한다.
    """

    def __init__(self, ttl_seconds: float = 180.0, step_timeout: float = 60.0):
        self._ttl = ttl_seconds
        self._step_timeout = step_timeout
        self._attempts: dict[str, _Attempt] = {}
        self._lock = threading.Lock()

    def start(
        self,
        run: Callable[[Callable[[str], str]], Any],
        *,
        meta: dict | None = None,
        timeout: float | None = None,
    ) -> tuple[str, tuple[str, Any]]:
        """`run(ask)`를 스레드에서 시작하고 (attempt_id, 첫 status)를 돌려준다.

        첫 status: OTP가 필요하면 ``(OTP_REQUESTED, None)``, OTP 없이 끝나면
        ``(DONE, result)``, 예외면 ``(ERROR, exc)``.
        """
        self.cleanup()
        attempt_id = uuid.uuid4().hex
        otp_in: queue.Queue = queue.Queue(maxsize=1)
        status_out: queue.Queue = queue.Queue()

        def ask(prompt: str = "") -> str:
            status_out.put((OTP_REQUESTED, None))
            code = otp_in.get()
            if code is None:
                raise OtpCancelled()
            return code

        def worker() -> None:
            try:
                result = run(ask)
            except OtpCancelled:
                return
            except Exception as exc:  # noqa: BLE001 - 웹 계층으로 전달
                status_out.put((ERROR, exc))
            else:
                status_out.put((DONE, result))

        thread = threading.Thread(target=worker, daemon=True)
        with self._lock:
            self._attempts[attempt_id] = _Attempt(
                otp_in, status_out, thread, time.monotonic(), meta or {}
            )
        thread.start()
        return attempt_id, self._await(attempt_id, status_out, timeout)

    def submit_otp(
        self, attempt_id: str, code: str, *, timeout: float | None = None
    ) -> tuple[str, Any]:
        """OTP 코드를 넣고 다음 status를 돌려준다 (재시도면 OTP_REQUESTED 다시)."""
        attempt = self._get(attempt_id)
        attempt.otp_in.put(code)
        return self._await(attempt_id, attempt.status_out, timeout)

    def cancel(self, attempt_id: str) -> None:
        """진행중 로그인을 버린다(스레드는 OtpCancelled로 조용히 종료)."""
        with self._lock:
            attempt = self._attempts.pop(attempt_id, None)
        if attempt is not None:
            _unblock(attempt)

    def cleanup(self) -> None:
        """TTL 지난 attempt를 만료 처리."""
        now = time.monotonic()
        with self._lock:
            expired = [a for a, at in self._attempts.items() if now - at.created_at > self._ttl]
            attempts = [self._attempts.pop(a) for a in expired]
        for attempt in attempts:
            _unblock(attempt)

    def active_count(self) -> int:
        with self._lock:
            return len(self._attempts)

    # -- internal ---------------------------------------------------------

    def _await(self, attempt_id: str, status_out: queue.Queue, timeout: float | None) -> tuple[str, Any]:
        try:
            status, payload = status_out.get(timeout=timeout or self._step_timeout)
        except queue.Empty:
            self.cancel(attempt_id)
            raise TimeoutError("login step timed out")
        if status in (DONE, ERROR):
            self._discard(attempt_id)
        return status, payload

    def _get(self, attempt_id: str) -> _Attempt:
        with self._lock:
            attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise AttemptNotFound(attempt_id)
        return attempt

    def _discard(self, attempt_id: str) -> None:
        with self._lock:
            self._attempts.pop(attempt_id, None)


def _unblock(attempt: _Attempt) -> None:
    """대기중인 로그인 스레드를 None으로 깨워 OtpCancelled 유도."""
    try:
        attempt.otp_in.put_nowait(None)
    except queue.Full:
        pass
