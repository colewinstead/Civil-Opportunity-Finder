"""Configurable relevance ranking, never a likelihood of winning work."""
from app.config import DEFAULT_WEIGHTS
from app.models.opportunity import Category
from app.services.classifier import contains_phrase

SIGNALS = {
    "civil": ("civil engineering", "engineer", "engineering"),
    "professional": ("professional engineering services", "professional civil engineering", "professional services", "engineering services"),
    "rfq_rfp": ("rfq", "rfp", "request for qualifications", "request for proposals"),
    "consulting": ("consulting", "consultant"),
    "design": ("design", "design services"),
    "unrelated": ("supplies only", "equipment purchase", "janitorial", "information technology", "IT services", "medical", "office supplies"),
}


def score_match(values: dict, category: Category, weights: dict[str, int] | None = None) -> int:
    weights = DEFAULT_WEIGHTS | (weights or {})
    text = " ".join(str(values.get(key) or "") for key in ("title", "description", "raw_text", "procurement_type"))
    enabled = {key: any(contains_phrase(text, phrase) for phrase in phrases) for key, phrases in SIGNALS.items()}
    enabled["professional"] |= values.get("professional_services") is True
    enabled["civil"] |= values.get("engineering_required") is True
    enabled["discipline"] = category != Category.OTHER
    enabled["mississippi"] = str(values.get("state") or "").casefold() in {"ms", "mississippi"}
    return max(0, min(100, sum(weights[key] for key, matched in enabled.items() if matched)))
