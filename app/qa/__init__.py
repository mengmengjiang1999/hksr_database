"""Evidence-grounded question answering."""

from app.qa.grounding import (
    answer_question,
    answer_question_legacy,
    evaluate_answers,
    ground_draft,
    validate_claims,
)
from app.qa.evaluation import (
    corpus_snapshot,
    evaluate_real_questions,
    load_real_question_dataset,
    load_taxonomy,
)
from app.qa.intent import build_query_plan, detect_intent, resolve_query_entities
from app.qa.generation import (
    GenerationService,
    build_evidence_packet,
    render_prompt,
    response_schema,
    validate_generated_response,
)

__all__ = [
    "answer_question", "answer_question_legacy", "corpus_snapshot", "evaluate_answers", "evaluate_real_questions",
    "GenerationService", "build_evidence_packet", "build_query_plan", "detect_intent",
    "ground_draft", "load_real_question_dataset", "render_prompt", "response_schema",
    "load_taxonomy", "resolve_query_entities", "validate_claims",
    "validate_generated_response",
]
