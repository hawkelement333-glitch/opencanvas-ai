from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise
from typing import Protocol

from openai import AsyncOpenAI

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents.errors import EmbeddingProviderError

_TOKENS = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int
    mock: bool

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbeddingProvider:
    name = "mock"
    model = "mock-term-hash-v1"
    dimensions = 1536
    mock = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_mock_embedding(text, self.dimensions) for text in texts]


class OpenAIEmbeddingProvider:
    name = "openai"
    mock = False

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int = 1536,
        batch_size: int = 64,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        client = AsyncOpenAI(api_key=self._api_key, timeout=self._timeout_seconds)
        try:
            for offset in range(0, len(texts), self._batch_size):
                batch = texts[offset : offset + self._batch_size]
                response = await client.embeddings.create(
                    input=batch,
                    model=self.model,
                    dimensions=self.dimensions,
                    encoding_format="float",
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                if len(ordered) != len(batch):
                    raise EmbeddingProviderError(
                        "The embedding provider returned an incomplete batch."
                    )
                vectors.extend(
                    _validate_vector(item.embedding, self.dimensions) for item in ordered
                )
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError("The embedding request failed.") from exc
        finally:
            await client.close()
        return vectors


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.effective_embedding_provider == "mock" or settings.openai_api_key is None:
        return MockEmbeddingProvider()
    return OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        timeout_seconds=settings.openai_timeout_seconds,
    )


def _mock_embedding(text: str, dimensions: int) -> list[float]:
    tokens = [token for token in _TOKENS.findall(text.lower()) if token not in _STOPWORDS]
    features = tokens + [f"{left}:{right}" for left, right in pairwise(tokens)]
    vector = [0.0] * dimensions
    if not features:
        vector[0] = 1.0
        return vector
    for feature in features:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    return _normalize(vector)


def _validate_vector(values: list[float], dimensions: int) -> list[float]:
    vector = [float(value) for value in values]
    if len(vector) != dimensions or not all(math.isfinite(value) for value in vector):
        raise EmbeddingProviderError("The embedding provider returned an invalid vector.")
    return _normalize(vector)


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise EmbeddingProviderError("The embedding provider returned a zero-length vector.")
    return [value / norm for value in vector]
