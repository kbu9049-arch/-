"""표준 라이브러리만 쓰는 HTTP 클라이언트 (속도 제한 + 재시도)."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from ingest import config


class RateLimiter:
    def __init__(self, per_sec: float):
        self.interval = 1.0 / per_sec if per_sec > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        gap = time.monotonic() - self._last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last = time.monotonic()


class HttpError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class Client:
    """GET 전용. 5xx·429·네트워크 오류는 지수 백오프로 재시도한다."""

    def __init__(self, rate_per_sec: float | None = None, timeout: int | None = None,
                 max_retries: int | None = None, verbose: bool = True):
        self.limiter = RateLimiter(rate_per_sec if rate_per_sec is not None
                                   else config.RATE_LIMIT_PER_SEC)
        self.timeout = timeout or config.REQUEST_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else config.MAX_RETRIES
        self.verbose = verbose
        self.requests = 0

    def get(self, url: str, params: dict | None = None) -> bytes:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            req = urllib.request.Request(url, headers={
                "User-Agent": config.USER_AGENT,
                "Accept": "application/json, text/xml;q=0.9, */*;q=0.5",
            })
            try:
                self.requests += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                body = e.read()[:400].decode("utf-8", "replace")
                # 4xx 는 우리 쪽 질의 문제이므로 재시도해도 소용없다. 429 만 예외.
                if e.code < 500 and e.code != 429:
                    raise HttpError(e.code, body) from e
                last_err = HttpError(e.code, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
            if attempt < self.max_retries:
                delay = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                if self.verbose:
                    print(f"    재시도 {attempt + 1}/{self.max_retries} ({last_err}) — {delay:.1f}초 대기")
                time.sleep(delay)
        raise RuntimeError(f"{self.max_retries}회 재시도 후 실패: {url}\n  마지막 오류: {last_err}")

    def get_json(self, url: str, params: dict | None = None) -> dict:
        raw = self.get(url, params)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JSON 파싱 실패 ({url}): {raw[:200]!r}") from e
