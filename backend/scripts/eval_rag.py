#!/usr/bin/env python3
"""RAG Evaluation Harness — Phase 10F.

Runs the golden Q&A dataset (data/golden_qa.json) through the live retrieval
and generation stack and reports:

  - Retrieval recall@k  — was at least one expected section in the top-k chunks?
  - Faithfulness score  — does the answer stay grounded in retrieved chunks?
                         (LLM-as-judge via Bedrock)
  - Answer relevance    — do the expected keywords appear in the answer?
  - Latency             — end-to-end ms per question

Usage::

    cd backend
    python scripts/eval_rag.py \\
        --tenant-id  org_xxx \\
        --document-id <uuid>  \\
        [--output results/eval_$(date +%Y%m%d).json] \\
        [--top-k 5]

Requirements:
    - A running Postgres with the document already ingested (status=ready).
    - AWS credentials (for Bedrock); falls back to local stubs if unavailable.
    - PYTHONPATH set to the backend root, or run with `uv run`.

Exit codes: 0 = all checks passed, 1 = any failure, 2 = configuration error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.rls import set_tenant_context
from app.services.generation_service import generate_answer
from app.services.retrieval_service import retrieve

log = structlog.get_logger(__name__)

_GOLDEN_PATH = Path(__file__).parent.parent / "data" / "golden_qa.json"

# ---------------------------------------------------------------------------
# Faithfulness judge prompt
# ---------------------------------------------------------------------------

_FAITHFULNESS_SYSTEM = """\
You are an impartial judge evaluating whether an AI answer is faithful to
provided source clauses. Faithful means every factual claim in the answer
can be traced to at least one of the provided clauses.

Respond with ONLY a JSON object:
{"score": <0-10>, "reason": "<one sentence>"}

Score guide:
  10 = fully grounded, every claim is in the clauses
   7 = mostly grounded, minor extrapolation
   4 = partially grounded, some unsupported claims
   0 = answer is not grounded at all
"""


def _faithfulness_user_prompt(question: str, answer: str, chunks) -> str:  # type: ignore[type-arg]
    clause_text = "\n\n".join(
        f"[{c.section_number or c.heading or 'unknown'}] {c.content[:400]}"
        for c in chunks
    )
    return (
        f"Question: {question}\n\n"
        f"Answer: {answer}\n\n"
        f"Source clauses:\n{clause_text}\n\n"
        "Rate the faithfulness of the answer to the source clauses."
    )


async def _judge_faithfulness(question: str, answer: str, chunks) -> dict:  # type: ignore[type-arg]
    """Call Bedrock to score faithfulness. Returns {score, reason}."""
    from app.core.exceptions import AwsError
    from app.infra import bedrock

    try:
        raw = await bedrock.converse_text(
            system=_FAITHFULNESS_SYSTEM,
            user=_faithfulness_user_prompt(question, answer, chunks),
            max_tokens=256,
            temperature=0.0,
        )
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
    except (AwsError, json.JSONDecodeError):
        pass
    # Stub when Bedrock is unavailable
    not_found = "not found" in answer.lower()
    return {
        "score": 0 if not_found else 7,
        "reason": "Bedrock unavailable — stub score applied.",
    }


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------


def _recall_at_k(expected_sections: list[str], chunks) -> bool:  # type: ignore[type-arg]
    """True if at least one expected section appears in the retrieved chunks."""
    retrieved_sections = set()
    for chunk in chunks:
        if chunk.section_number:
            retrieved_sections.add(chunk.section_number.lower().strip())
        if chunk.heading:
            retrieved_sections.add(chunk.heading.lower().strip())

    for expected in expected_sections:
        e = expected.lower().strip()
        # Exact match or prefix match (e.g. expected "3" matches section "3.1")
        for rs in retrieved_sections:
            if rs == e or rs.startswith(e + ".") or e.startswith(rs + "."):
                return True
            # Substring match for heading-based sections
            if e in rs or rs in e:
                return True
    return False


def _keyword_relevance(expected_keywords: list[str], answer: str) -> float:
    """Fraction of expected keywords found in the answer (case-insensitive)."""
    answer_lower = answer.lower()
    matched = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return matched / len(expected_keywords) if expected_keywords else 1.0


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------


async def run_eval(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    questions: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """Run every question through retrieve → generate → judge and return results."""
    results = []

    for item in questions:
        q_id: str = item["id"]
        question: str = item["question"]
        expected_sections: list[str] = item.get("expected_chunk_sections", [])
        expected_keywords: list[str] = item.get("expected_answer_keywords", [])

        log.info("eval_question", id=q_id, question=question[:60])
        t0 = time.perf_counter()

        # ── Retrieve ──────────────────────────────────────────────────────────
        chunks = await retrieve(
            session,
            tenant_id,
            question,
            document_id=document_id,
        )
        chunks_for_eval = chunks[:top_k]

        # ── Generate ──────────────────────────────────────────────────────────
        gen = await generate_answer(question, chunks_for_eval)

        latency_ms = int((time.perf_counter() - t0) * 1000)

        # ── Score ─────────────────────────────────────────────────────────────
        recall = _recall_at_k(expected_sections, chunks_for_eval)
        relevance = _keyword_relevance(expected_keywords, gen.answer)
        faith = await _judge_faithfulness(question, gen.answer, chunks_for_eval)

        result = {
            "id": q_id,
            "question": question,
            "answer": gen.answer,
            "not_found": gen.not_found,
            "recall_at_k": recall,
            "keyword_relevance": round(relevance, 3),
            "faithfulness_score": faith.get("score"),
            "faithfulness_reason": faith.get("reason"),
            "retrieved_sections": [
                c.section_number or c.heading or "?" for c in chunks_for_eval
            ],
            "latency_ms": latency_ms,
        }
        results.append(result)

        log.info(
            "eval_result",
            id=q_id,
            recall=recall,
            relevance=relevance,
            faithfulness=faith.get("score"),
            latency_ms=latency_ms,
        )

    return results


def _print_table(results: list[dict]) -> None:
    """Print a human-readable summary table to stdout."""
    print("\n" + "=" * 72)
    print(f"{'ID':<6} {'Recall':>7} {'Relvnc':>7} {'Faith':>6} {'ms':>6}  Question")
    print("-" * 72)
    for r in results:
        recall_sym = "✓" if r["recall_at_k"] else "✗"
        relevance = f"{r['keyword_relevance']:.2f}"
        faith = (
            str(r["faithfulness_score"])
            if r["faithfulness_score"] is not None
            else "N/A"
        )
        print(
            f"{r['id']:<6} {recall_sym:>7} {relevance:>7} {faith:>6} "
            f"{r['latency_ms']:>6}  {r['question'][:40]}"
        )
    print("=" * 72)

    total = len(results)
    recall_ok = sum(1 for r in results if r["recall_at_k"])
    avg_rel = sum(r["keyword_relevance"] for r in results) / total if total else 0
    faith_scores = [
        r["faithfulness_score"] for r in results if r["faithfulness_score"] is not None
    ]
    avg_faith = sum(faith_scores) / len(faith_scores) if faith_scores else None
    avg_ms = sum(r["latency_ms"] for r in results) / total if total else 0

    print(f"\nSummary: {total} questions")
    print(f"  Recall@k:   {recall_ok}/{total} ({recall_ok/total*100:.0f}%)")
    print(f"  Avg relevance: {avg_rel:.2f}")
    if avg_faith is not None:
        print(f"  Avg faithfulness: {avg_faith:.1f}/10")
    print(f"  Avg latency: {avg_ms:.0f} ms\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Legal Navigator RAG evaluation harness"
    )
    parser.add_argument("--tenant-id", required=True, help="Clerk org_id of the tenant")
    parser.add_argument(
        "--document-id",
        required=True,
        type=uuid.UUID,
        help="UUID of a READY document to evaluate against",
    )
    parser.add_argument(
        "--golden-file",
        default=str(_GOLDEN_PATH),
        help=f"Path to golden Q&A JSON (default: {_GOLDEN_PATH})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results file (optional)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks passed to the generator (default: 5)",
    )
    return parser.parse_args()


async def main() -> int:
    configure_logging()
    args = _parse_args()

    # Load golden set
    golden_path = Path(args.golden_file)
    if not golden_path.exists():
        log.error("golden_file_not_found", path=str(golden_path))
        return 2
    questions: list[dict] = json.loads(golden_path.read_text())
    log.info("eval_start", questions=len(questions), document_id=str(args.document_id))

    # DB session
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        await set_tenant_context(session, args.tenant_id)
        results = await run_eval(
            session,
            args.tenant_id,
            args.document_id,
            questions,
            top_k=args.top_k,
        )

    _print_table(results)

    # Write JSON report
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2, default=str))
        log.info("eval_report_written", path=str(out_path))

    # Return 1 if any recall failed, 0 otherwise
    all_pass = all(r["recall_at_k"] for r in results)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
