"""LLM-as-judge evaluators for RAG generation quality.

Each judge evaluates one criterion (faithfulness, relevancy, correctness)
via a structured LLM call. Two providers:

- ollama   — local model over HTTP; JSON is requested in the prompt and
             extracted defensively (Ollama has no schema enforcement).
- anthropic — Claude via the official SDK with structured outputs
             (messages.parse), so the response is schema-validated rather
             than scraped from free text.

Design principles:
- One criterion per call (more reliable than multi-criterion)
- 3-point scales for relevancy/correctness (more reliable than 5-point)
- Chain-of-thought reasoning captured alongside the score
- Structured/validated JSON output

Note on determinism: the Ollama path uses temperature 0. The Claude path does
NOT set temperature — current Claude models (Opus 4.8 / Sonnet 4.6) reject
`temperature` (and `top_p`/`top_k`); behavior is steered via the prompt instead.
"""

import json
import logging
import re
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from shared.config import settings

log = logging.getLogger(__name__)

FAITHFULNESS_PROMPT = """You are evaluating whether an AI answer is faithful to the provided context.
A faithful answer ONLY contains information that can be verified from the context.

## Context:
{context}

## Answer:
{answer}

## Instructions:
1. List each factual claim made in the answer.
2. For each claim, check if the context supports it.
3. Classify each claim as SUPPORTED, CONTRADICTED, or NOT_FOUND.
4. Calculate faithfulness_score = count(SUPPORTED) / count(all_claims).

Respond ONLY with JSON (no markdown, no extra text):
{{"claims": [{{"claim": "...", "verdict": "SUPPORTED|CONTRADICTED|NOT_FOUND"}}], "faithfulness_score": 0.0, "reasoning": "..."}}"""


RELEVANCY_PROMPT = """You are evaluating whether an AI answer addresses the user's question.

## Question:
{question}

## Answer:
{answer}

## Instructions:
Rate how well the answer addresses the question.

Score:
- 3 = Directly and completely answers the question
- 2 = Partially answers or is tangentially related
- 1 = Does not answer the question

Respond ONLY with JSON (no markdown, no extra text):
{{"score": 1, "reasoning": "..."}}"""


CORRECTNESS_PROMPT = """You are comparing an AI answer against a reference answer for factual correctness.
Focus on factual content, not wording. Minor phrasing differences are acceptable.

## Question:
{question}

## Reference Answer:
{expected_answer}

## AI Answer:
{actual_answer}

## Instructions:
Rate the correctness of the AI answer compared to the reference.

Score:
- 3 = Conveys the same key facts as the reference
- 2 = Partially correct, missing or adding some facts
- 1 = Incorrect or contradicts the reference

Respond ONLY with JSON (no markdown, no extra text):
{{"score": 1, "reasoning": "..."}}"""


# --- Structured output schemas (used by the Claude path) ---


class _Claim(BaseModel):
    claim: str
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_FOUND"]


class FaithfulnessJudgment(BaseModel):
    claims: list[_Claim] = Field(default_factory=list)
    faithfulness_score: float
    reasoning: str = ""


class ScoreJudgment(BaseModel):
    score: int  # 1-3
    reasoning: str = ""


def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>\s*", "", text).strip()


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM output, handling markdown fences."""
    text = _strip_think_tags(text)
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code fence
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if match:
        return json.loads(match.group(1))
    # Try finding first { ... } block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"Could not extract JSON from: {text[:200]}")


class LLMJudge:
    """LLM-based evaluator for RAG generation quality."""

    def __init__(
        self,
        provider: str = "ollama",
        model: str | None = None,
        temperature: float = 0.0,
    ):
        self.provider = provider
        self.model = model or self._default_model(provider)
        self.temperature = temperature
        self._anthropic_client = None

    @staticmethod
    def _default_model(provider: str) -> str:
        if provider == "anthropic":
            return settings.anthropic_model
        return settings.ollama_model

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic

            # The SDK reads ANTHROPIC_API_KEY from the environment; pass the
            # configured key explicitly only when one is set in settings.
            if settings.anthropic_api_key:
                self._anthropic_client = anthropic.Anthropic(
                    api_key=settings.anthropic_api_key
                )
            else:
                self._anthropic_client = anthropic.Anthropic()
        return self._anthropic_client

    # --- Provider calls ---

    def _call_ollama(self, prompt: str) -> str:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = client.post(
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": f"/nothink\n{prompt}"},
                    ],
                    "stream": False,
                    "options": {"temperature": self.temperature},
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    def _call_anthropic_parse(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """Call Claude with structured outputs; returns a validated model.

        No temperature/thinking config — current Claude models reject sampling
        params, and adaptive thinking (off by default here) isn't needed for
        a short structured judgment.
        """
        client = self._get_anthropic_client()
        message = client.messages.parse(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        return message.parsed_output

    # --- Criteria ---

    def evaluate_faithfulness(self, answer: str, context: str) -> float:
        """Score faithfulness (0-1). Higher = more faithful to context."""
        prompt = FAITHFULNESS_PROMPT.format(context=context, answer=answer)
        try:
            if self.provider == "anthropic":
                result: FaithfulnessJudgment = self._call_anthropic_parse(
                    prompt, FaithfulnessJudgment
                )
                score, n_claims = result.faithfulness_score, len(result.claims)
            else:
                data = _extract_json(self._call_ollama(prompt))
                score = float(data.get("faithfulness_score", 0.0))
                n_claims = len(data.get("claims", []))
            log.debug(f"Faithfulness: {score:.2f} ({n_claims} claims)")
            return max(0.0, min(1.0, score))
        except Exception as e:
            log.warning(f"Faithfulness judge failed: {e}")
            return 0.0

    def evaluate_relevancy(self, question: str, answer: str) -> int:
        """Score relevancy (1-3). 3 = directly answers the question."""
        prompt = RELEVANCY_PROMPT.format(question=question, answer=answer)
        return self._score_criterion(prompt, "Relevancy")

    def evaluate_correctness(
        self, question: str, expected_answer: str, actual_answer: str
    ) -> int:
        """Score correctness (1-3). 3 = matches reference answer."""
        prompt = CORRECTNESS_PROMPT.format(
            question=question,
            expected_answer=expected_answer,
            actual_answer=actual_answer,
        )
        return self._score_criterion(prompt, "Correctness")

    def _score_criterion(self, prompt: str, label: str) -> int:
        try:
            if self.provider == "anthropic":
                result: ScoreJudgment = self._call_anthropic_parse(prompt, ScoreJudgment)
                score = result.score
            else:
                data = _extract_json(self._call_ollama(prompt))
                score = int(data.get("score", 1))
            return max(1, min(3, score))
        except Exception as e:
            log.warning(f"{label} judge failed: {e}")
            return 1
