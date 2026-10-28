"""Small SQLite-backed RAG index for the application's generic playbooks."""
import math

from rules import RULES
from .ai import AIServiceError, _client
from .models import KnowledgeChunk

PLAYBOOK_DETAILS = {
    "UNCONFIRMED": "When an order remains unconfirmed beyond the configured limit, verify the order and contact the customer to confirm intent. For COD, verify the delivery address. Do not promise dispatch until confirmed.",
    "DISPATCH_DELAY": "When a confirmed order has not been dispatched beyond the configured limit, ask the warehouse to pack and hand the order to the courier, then record the dispatch date. Do not tell the customer it has shipped before confirmation.",
    "SHIPMENT_DELAY": "When the expected delivery date has passed for a dispatched order, check the courier tracking, confirm the current shipment status, and share a revised delivery estimate only after it is verified.",
    "FAILED_DELIVERY": "After a failed delivery attempt, verify the customer's address and availability, then request a courier re-attempt. Record the confirmed outcome and avoid assuming the customer caused the failure.",
    "HIGH_VALUE_OVERDUE": "For a high-value undelivered order past its expected date, escalate to the manager, verify courier status, and contact the customer with confirmed information. Do not promise refunds or compensation without authorization.",
}


def playbook_entries():
    return [(code, RULES[code], f"{RULES[code]}\n{PLAYBOOK_DETAILS[code]}") for code in RULES]


def _embed(text, task_type):
    import os
    try:
        from google.genai import types
        response = _client().models.embed_content(
            model=os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"), contents=text,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=768),
        )
        return list(response.embeddings[0].values)
    except AIServiceError:
        raise
    except Exception as exc:
        raise AIServiceError(f"Could not create Gemini embeddings ({type(exc).__name__}). Check the API key and embedding quota.") from exc


def index_playbooks():
    """Create or refresh embeddings for the static rule playbooks only."""
    entries = playbook_entries()
    existing = {chunk.source: chunk for chunk in KnowledgeChunk.objects.all()}
    for code, title, content in entries:
        chunk = existing.get(code)
        if chunk and chunk.content == content and chunk.embedding:
            continue
        vector = _embed(content, "RETRIEVAL_DOCUMENT")
        KnowledgeChunk.objects.update_or_create(
            source=code, defaults={"rule_code": code, "content": content, "embedding": vector}
        )
    KnowledgeChunk.objects.exclude(source__in=[entry[0] for entry in entries]).delete()
    return len(entries)


def retrieve_playbook(query, rule_code=None, limit=3):
    """Return relevant playbook text and source labels using cosine similarity."""
    chunks = list(KnowledgeChunk.objects.all())
    if not chunks:
        index_playbooks()
        chunks = list(KnowledgeChunk.objects.all())
    if not chunks:
        return "", []
    vector = _embed(query, "RETRIEVAL_QUERY")
    norm = math.sqrt(sum(v * v for v in vector)) or 1
    ranked = []
    for chunk in chunks:
        values = chunk.embedding
        if len(values) != len(vector):
            continue
        vnorm = math.sqrt(sum(v * v for v in values)) or 1
        score = sum(a * b for a, b in zip(vector, values)) / (norm * vnorm)
        if rule_code and chunk.rule_code == rule_code:
            score += 0.15
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    matches = ranked[:limit]
    return "\n\n".join(chunk.content for _, chunk in matches), [chunk.source for _, chunk in matches]
