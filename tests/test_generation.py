import asyncio
import json

import pytest

from services.query import generator
from shared.config import settings


def test_generation_context_is_bounded(monkeypatch, chunk):
    monkeypatch.setattr(settings, "context_max_chars", 1000)
    chunks = [chunk.model_copy(update={"content": "a" * 10000}) for _ in range(30)]
    assert len(generator._build_context(chunks)) <= 1000


class FakeResponse:
    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for item in self.data:
            yield json.dumps(item)


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def stream(self, method, url, **kwargs):
        assert kwargs["json"]["options"]["num_predict"] == settings.generation_max_tokens
        return self.response


def test_generation_rejects_unfinished_inference_stream(monkeypatch, chunk):
    fake = FakeClient(FakeResponse([{"message": {"content": "partial"}}]))
    monkeypatch.setattr(generator.httpx, "AsyncClient", lambda **kwargs: fake)

    async def collect():
        return [part async for part in generator.generate_stream("q", [chunk])]

    with pytest.raises(RuntimeError, match="without completion"):
        asyncio.run(collect())


def test_stream_sanitization_and_explicit_completion(monkeypatch, chunk):
    fake = FakeClient(
        FakeResponse(
            [
                {"message": {"content": "<thi"}},
                {"message": {"content": "nk>private"}},
                {"message": {"content": "</think>answer"}},
                {"done": True},
            ]
        )
    )
    monkeypatch.setattr(generator.httpx, "AsyncClient", lambda **kwargs: fake)

    async def collect():
        return [part async for part in generator.generate_stream("q", [chunk])]

    assert asyncio.run(collect()) == ["answer"]
