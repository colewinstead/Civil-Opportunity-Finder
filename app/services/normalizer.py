"""Conservative normalization: unknown or ambiguous source fields remain null."""
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from app.schemas.opportunity import OpportunityInput


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(unicodedata.normalize("NFKC", value).split()) or None


def normalized_key(value: str | None) -> str:
    return re.sub(r"[^\w]+", " ", clean_text(value or "").casefold()).strip() if clean_text(value) else ""


def canonical_url(value: str | None, base_url: str | None = None) -> str | None:
    if not value:
        return None
    parts = urlsplit(urljoin(base_url or "", value.strip()))
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Unsafe or incomplete source URL")
    # Preserve parameters that might identify a solicitation; remove only tracking.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parts.port and not ((parts.scheme == "https" and parts.port == 443) or (parts.scheme == "http" and parts.port == 80)):
        host += f":{parts.port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(sorted(query)), ""))


def parse_date(value: str | date | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) or value is None:
        return value
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    return None


def normalize_record(raw: dict) -> OpportunityInput:
    values = raw.copy()
    for key, value in values.items():
        if isinstance(value, str) and key != "raw_text":
            values[key] = clean_text(value)
    values["source_url"] = canonical_url(values.get("source_url"))
    values["opportunity_url"] = canonical_url(values.get("opportunity_url"), values["source_url"])
    for key in ("posted_date", "due_date"):
        values[key] = parse_date(values.get(key))
    if values.get("state") and values["state"].casefold() in {"ms", "mississippi"}:
        values["state"] = "MS"
    if values.get("contact_email"):
        values["contact_email"] = values["contact_email"].removeprefix("mailto:").casefold()
    if values.get("contact_phone"):
        values["contact_phone"] = re.sub(r"\s+", " ", values["contact_phone"].removeprefix("tel:"))
    if values.get("procurement_type"):
        values["procurement_type"] = values["procurement_type"].upper()
    return OpportunityInput.model_validate(values)


def content_hash(values: dict) -> str:
    """Hash source content independently of discovery times and user decisions."""
    excluded = {"id", "first_seen", "last_seen", "status", "match_score", "category", "subcategories", "content_hash"}
    payload = {k: v for k, v in values.items() if k not in excluded}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
