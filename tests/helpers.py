import json
from pathlib import Path

import httpx

from career_agent.discovery.http import PublicJobClient
from career_agent.models.job import EmployerBoard

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(provider):
    return json.loads((FIXTURES / f"{provider}.json").read_text())


def board(provider="greenhouse"):
    return EmployerBoard(
        name="Example",
        domain="example.test",
        provider=provider,
        board="example",
        careers_url="https://example.test/careers",
    )


def client_for(value, handler=None, **kwargs):
    transport = httpx.MockTransport(handler or (lambda r: httpx.Response(200, json=value)))
    return PublicJobClient(transport=transport, sleeper=lambda _: None, **kwargs)
