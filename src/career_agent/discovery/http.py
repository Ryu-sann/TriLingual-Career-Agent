import json
import time

import httpx

from career_agent.models.job import PROVIDER_HOSTS


class DiscoveryError(Exception):
    """Safe error codes only: never include response bodies or exception strings."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PublicJobClient:
    def __init__(
        self,
        *,
        transport=None,
        interval=0.5,
        retries=2,
        sleeper=time.sleep,
        clock=time.monotonic,
        max_bytes=30_000_000,
    ):
        if interval < 0.1 or retries not in range(4):
            raise ValueError("Unsafe rate-limit configuration")
        self.client = httpx.Client(
            transport=transport,
            timeout=30,
            follow_redirects=False,
            headers={
                "User-Agent": "TriLingualCareerAgent/0.2 public-jobs",
                "Accept": "application/json",
            },
        )
        self.interval, self.retries = interval, retries
        self.sleeper, self.clock = sleeper, clock
        self.max_bytes = max_bytes
        self.last_request = {}

    def get_json(self, url: str, params=None):
        parsed = httpx.URL(url)
        if (
            parsed.scheme != "https"
            or parsed.host not in PROVIDER_HOSTS.values()
            or parsed.port not in {None, 443}
            or parsed.userinfo
        ):
            raise DiscoveryError("destination_not_allowed")
        for attempt in range(self.retries + 1):
            previous = self.last_request.get(parsed.host)
            if previous is not None:
                self.sleeper(max(0, previous + self.interval - self.clock()))
            self.last_request[parsed.host] = self.clock()
            try:
                with self.client.stream("GET", url, params=params) as response:
                    if response.status_code in {429, 502, 503, 504} and attempt < self.retries:
                        retry_after = response.headers.get("Retry-After", "")
                        delay = (
                            min(30.0, max(1.0, float(retry_after)))
                            if retry_after.isdigit()
                            else min(8.0, 2.0**attempt)
                        )
                        self.sleeper(delay)
                        continue
                    if response.status_code != 200:
                        raise DiscoveryError(f"http_{response.status_code}")
                    if "application/json" not in response.headers.get("Content-Type", ""):
                        raise DiscoveryError("unexpected_content_type")
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_bytes:
                            raise DiscoveryError("response_too_large")
                    return json.loads(content)
            except httpx.TransportError as exc:
                raise DiscoveryError("transport_error") from exc
            except (ValueError, UnicodeError) as exc:
                raise DiscoveryError("invalid_json") from exc
        raise DiscoveryError("retry_limit")

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
