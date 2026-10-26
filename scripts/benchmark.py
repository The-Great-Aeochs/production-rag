"""Bounded HTTP load probe. Measures a specified workload; sets no fake baseline.

RAG_API_TOKEN=<token> python -m scripts.benchmark --queries queries.json --concurrency 4 --requests 100
Queries JSON is a list of question strings. Output is JSON; auth tokens are never printed.
"""

import argparse
import asyncio
import json
import math
import os
import time
from pathlib import Path

import httpx


def percentile(values, percent):
    return sorted(values)[max(0, math.ceil(len(values) * percent / 100) - 1)] if values else None


async def benchmark(
    url: str, token: str, queries: list[str], concurrency: int, count: int, use_cache: bool
):
    latencies = []
    codes = {}
    started = time.monotonic()
    counter = iter(range(count))
    async with httpx.AsyncClient(
        base_url=url,
        timeout=120,
        headers={"Authorization": f"Bearer {token}"},
        limits=httpx.Limits(max_connections=concurrency),
    ) as client:

        async def worker():
            for index in counter:
                t0 = time.monotonic()
                try:
                    response = await client.post(
                        "/query",
                        json={
                            "query": queries[index % len(queries)],
                            "use_cache": use_cache,
                        },
                    )
                    code = str(response.status_code)
                    if response.is_success:
                        latencies.append((time.monotonic() - t0) * 1000)
                except httpx.HTTPError:
                    code = "transport_error"
                codes[code] = codes.get(code, 0) + 1

        await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.monotonic() - started
    return {
        "requests": count,
        "concurrency": concurrency,
        "use_cache": use_cache,
        "duration_s": round(elapsed, 3),
        "completed_requests_per_second": count / elapsed,
        "status_counts": codes,
        "successes": len(latencies),
        "success_latency_p50_ms": percentile(latencies, 50),
        "success_latency_p95_ms": percentile(latencies, 95),
    }


def main():
    parser = argparse.ArgumentParser(description="Measure API throughput and latency")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--use-cache", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("RAG_API_TOKEN")
    queries = json.loads(args.queries.read_text())
    if (
        not token
        or not isinstance(queries, list)
        or not queries
        or not all(isinstance(q, str) and q.strip() for q in queries)
    ):
        parser.error("Set RAG_API_TOKEN and provide a nonempty JSON list of questions")
    if not 1 <= args.concurrency <= 128 or not 1 <= args.requests <= 100000:
        parser.error("Concurrency must be 1-128; requests must be 1-100000")
    result = asyncio.run(
        benchmark(args.url, token, queries, args.concurrency, args.requests, args.use_cache)
    )
    print(json.dumps(result, indent=2))
    if result["successes"] != args.requests:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
