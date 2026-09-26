"""Public Mississippi procurement search: paginated JSON and individual RFx details.

The endpoints are those used by the portal's own search page. No document
downloads, authentication, browser automation, or source-specific scoring.
"""
import json
import logging
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.models.opportunity import Category
from app.schemas.opportunity import OpportunityInput
from app.scrapers.base import BaseScraper, ScraperError, SourceAccessError
from app.services.classifier import classify, procurement_product_signals
from app.services.normalizer import clean_text, parse_date

logger = logging.getLogger("opportunity_finder.scrapers.mississippi_procurement")


class MississippiProcurementScraper(BaseScraper):
    slug = "mississippi-procurement"
    source_name = "Mississippi Procurement Opportunity and Public Notification Search"
    source_url = "https://www.ms.gov/dfa/contract_bid_search/bid"
    default_active = True
    notes = ("Public open solicitations; engineering services and civil infrastructure bids. "
             "Descriptions can be truncated by the portal. Documents are linked, not downloaded. "
             "Closing times remain in raw text; closing timezone is not stated by the portal.")
    endpoint_root = "https://www.ms.gov/dfa/contract_bid_search/Bid"
    listing_url = endpoint_root + "/BidData?AppId=1&Status=Open"
    page_size = 100
    max_pages = 100
    columns = ("Agency", "BidNumber", "ObjectID", "VerNumber", "BidStatus",
               "AdvertiseDate", "SubmissionDate", "OpeningDate", "BidID")

    @classmethod
    def listing_form(cls, offset: int) -> dict[str, str]:
        """DataTables' legacy server-side form, sorted by stable ascending BidID."""
        form = {"sEcho": "1", "iDisplayStart": str(offset), "iDisplayLength": str(cls.page_size),
                "iColumns": str(len(cls.columns)), "iSortingCols": "1", "iSortCol_0": "8",
                "sSortDir_0": "asc", "sSearch": "", "bRegex": "false", "sColumns": ""}
        for index, name in enumerate(cls.columns):
            form.update({f"mDataProp_{index}": name, f"bSearchable_{index}": "true",
                         f"bSortable_{index}": "true", f"sSearch_{index}": "",
                         f"bRegex_{index}": "false"})
        return form

    @staticmethod
    def decode(content: str) -> dict:
        try:
            result = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise ScraperError("Procurement endpoint did not return valid JSON") from exc
        if not isinstance(result, dict):
            raise ScraperError("Procurement response must be a JSON object")
        return result

    @classmethod
    def parse_listing_page(cls, content: str) -> tuple[list[dict], int]:
        payload = cls.decode(content)
        rows, total = payload.get("aaData"), payload.get("iTotalDisplayRecords")
        if not isinstance(rows, list) or type(total) is not int or total < 0:
            raise ScraperError("Unexpected procurement listing structure/count")
        return rows, total

    @staticmethod
    def text(value) -> str:
        """Clean source HTML as text, never render or execute source markup."""
        if value is None:
            return ""
        return clean_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)) or ""

    @classmethod
    def is_candidate(cls, row: dict) -> bool:
        # Major categories can be wrong: a real utility construction notice was
        # filed as COMMODITIES. Review details before excluding those categories.
        notification = str(row.get("SubProcurementCategoryID", "")).lstrip("0")
        return notification not in ("13", "14", "15")

    @classmethod
    def engineering_product(cls, record: dict) -> bool:
        return any(isinstance(item, dict) and str(item.get("CategoryNumber", "")).startswith("925")
                   for item in record.get("Items") or [])

    @classmethod
    def is_relevant(cls, record: dict) -> bool:
        text = " ".join(cls.text(record.get(key)) for key in ("BidDescription", "AdditionalInfo"))
        text += " " + " ".join(cls.text(item.get("Description")) for item in record.get("Attachments") or [] if isinstance(item, dict))
        signals = procurement_product_signals(record.get("Items") or [])
        text += " " + signals
        engineering = cls.engineering_product(record) or bool(
            re.search(r"\b(?:civil engineering|engineering services|surveying services)\b", text, re.I))
        # Road materials, highway-patrol uniforms and software can contain civil
        # words. A mislabeled commodity/IT record needs evidence of civil services.
        if str(record.get("ProcurementCategoryID", "")).lstrip("0") in ("2", "4"):
            return bool(signals) or engineering
        category, _ = classify(text)
        architecture_rfq = any(isinstance(item, dict) and str(item.get("CategoryNumber", "")).startswith("906")
                               for item in record.get("Items") or []) and bool(
            re.search(r"\bRFQ\b|statements of qualifications|request for qualifications", text, re.I))
        # Retain potential civil work when a construction notice describes a
        # park project or lists water tanks/well pumps, even if its scope is cut
        # off. These are review candidates, not assertions of engineering scope.
        construction = str(record.get("ProcurementCategoryID", "")).lstrip("0") == "3"
        water_construction = construction and any(
            isinstance(item, dict) and str(item.get("CategoryNumber", "")) in ("72090", "83073")
            for item in record.get("Items") or [])
        park_construction = construction and bool(re.search(r"\bconstruction\b.{0,200}\bpark\b", text, re.I))
        return category != Category.OTHER or bool(signals) or engineering or architecture_rfq or water_construction or park_construction

    def warn_record(self, identifier, error: Exception | str) -> None:
        message = f"Bid {identifier}: {error}"
        self.record_errors.append(message)
        self.metrics["malformed_skipped"] = self.metrics.get("malformed_skipped", 0) + 1
        logger.warning("Procurement record could not be fully collected",
                       extra={"fields": {"source": self.slug, "bid_id": identifier, "error": str(error)}})

    def fetch(self) -> str:
        if self.http is None:
            raise ScraperError("HTTP client was not configured")
        self.metrics = {"pages_fetched": 0, "detail_requests": 0, "records_discovered": 0,
                        "records_parsed": 0, "records_normalized": 0, "malformed_skipped": 0,
                        "records_excluded_listing": 0, "records_excluded_relevance": 0}
        self.record_errors = []
        rows, seen, expected = [], set(), None
        offset = 0
        for _ in range(self.max_pages):
            content = self.http.post_form(self.listing_url, self.listing_form(offset))
            self.metrics["pages_fetched"] += 1
            page, total = self.parse_listing_page(content)
            if expected is not None and total != expected:
                raise ScraperError("Listing count changed during pagination; retry collection later")
            expected = total
            if len(page) > self.page_size or offset + len(page) > total:
                raise ScraperError("Listing returned inconsistent pagination counts")
            if not page and offset < total:
                raise ScraperError("Listing stopped before all pages were collected")
            for row in page:
                if not isinstance(row, dict) or type(row.get("BidID")) is not int or row["BidID"] <= 0:
                    self.warn_record("unknown", "Missing or invalid stable BidID")
                    continue
                if row["BidID"] in seen:
                    raise ScraperError("Listing repeated a BidID across pages; refusing incomplete collection")
                seen.add(row["BidID"])
                rows.append(row)
            offset += len(page)
            self.metrics["records_discovered"] = offset
            if offset == total:
                break
        else:
            raise ScraperError("Procurement pagination exceeded its safety limit")
        details = []
        consecutive_failures = 0
        for row in rows:
            if not self.is_candidate(row):
                self.metrics["records_excluded_listing"] += 1
                continue
            bid_id = row["BidID"]
            self.metrics["detail_requests"] += 1
            try:
                detail = self.decode(self.http.get(f"{self.endpoint_root}/BidDetailData/{bid_id}"))
                if detail.get("BidID") != bid_id:
                    raise ScraperError("Detail identifier does not match listing")
                details.append(row | detail)
                consecutive_failures = 0
            except SourceAccessError:
                raise
            except ScraperError as exc:
                self.warn_record(bid_id, exc)
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    raise ScraperError("Three consecutive detail failures; defer collection") from exc
        return json.dumps({"records": details})

    @staticmethod
    def source_date(value) -> date | None:
        """Decode .NET local-date epochs; keep deadlines date-only in the model."""
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value.date() if isinstance(value, datetime) else value
        match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", str(value))
        if match:
            return datetime.fromtimestamp(int(match[1]) / 1000, timezone.utc).astimezone(
                ZoneInfo("America/Chicago")).date()
        parsed = parse_date(value)
        if parsed:
            return parsed
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            for format_ in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p"):
                try:
                    return datetime.strptime(str(value), format_).date()
                except ValueError:
                    continue
        raise ValueError(f"Malformed source date: {value!r}")

    @classmethod
    def parse_detail(cls, record: dict) -> dict:
        bid_id = record.get("BidID")
        if type(bid_id) is not int or bid_id <= 0:
            raise ValueError("Missing stable BidID")
        description = cls.text(record.get("BidDescription"))
        if not description:
            raise ValueError("Missing solicitation description/title")
        extra = cls.text(record.get("AdditionalInfo"))
        agency = cls.text(record.get("Agency")) or None
        issuer = re.match(r"(?:The\s+)?(.{3,120}?)\s+requests\s+(?:statements|proposals|qualifications)\b",
                          description, re.I)
        if agency == "MPTAP" and issuer:
            agency = issuer[1].strip()
        elif agency == "MPTAP":
            # Public bid notices often state the receiving entity instead of
            # a requests-proposals sentence. Extract only explicitly named issuers.
            receiver = re.search(
                r"received by\s+(?:the\s*)?((?:Board of Supervisors of\s+[A-Z][\w ]+? County)|"
                r"(?:(?:City|Town) of\s+[A-Z][\w ]+?)|(?:[A-Z][\w ]+? (?:District|Authority)))"
                r"(?=\s*\(|,|\s+(?:in|at|will)\b)", description)
            if receiver:
                agency = receiver[1].strip()
        county = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?) County\b", agency or "")
        if not county:
            county = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?) County\b", description)
        city = re.fullmatch(r"(?:City|Town) of (.+)", agency or "")
        title = description if len(description) <= 180 else description[:177].rsplit(" ", 1)[0] + "…"
        attachments = record.get("Attachments") or []
        labels = " ".join(cls.text(item.get("Description")) for item in attachments if isinstance(item, dict))
        solicitation_text = f"{description} {labels}"
        procurement = cls.text(record.get("BidType")) or None
        if re.search(r"\bRFQ\b|requests statements of qualifications|request for qualifications", solicitation_text, re.I):
            procurement = "RFQ"
        elif re.search(r"\bRFP\b|requests proposals|request for proposals", solicitation_text, re.I):
            procurement = "RFP"
        engineering = cls.engineering_product(record) or bool(re.search(r"\bengineering services\b", description, re.I))
        professional = engineering and (str(record.get("ProcurementCategoryID", "")).lstrip("0") == "1"
                                       or procurement in ("RFQ", "RFP"))
        contact_name = cls.text(record.get("BuyerName")) or None
        contact_email = cls.text(record.get("BuyerEmail")) or None
        contact = re.search(r"questions\s+contact\s+([^,\n]+),\s*([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", extra, re.I)
        if contact and (not contact_name or contact_name.upper() in ("BID BANK", "BIDBANK")):
            contact_name, contact_email = contact[1].strip(), contact[2]
        raw = [f"Bid ID: {bid_id}", f"RFx: {record.get('ObjectID') or ''}",
               f"Smart number: {record.get('BidNumber') or ''}", f"Publisher agency: {record.get('Agency') or ''}",
               f"Source procurement type: {record.get('BidType') or ''}", description, extra]
        for field in ("AdvertiseDate", "AdvertiseTime", "SubmissionDate", "SubmissionTime", "OpeningDate", "OpeningTime"):
            if record.get(field):
                raw.append(f"{field}: {record[field]}")
        raw.append("Closing timezone: not stated by the source; date-only deadline stored.")
        for item in record.get("Items") or []:
            if isinstance(item, dict):
                raw.append(f"Product: {item.get('CategoryNumber', '')} {cls.text(item.get('CategoryDescription'))}")
        for item in attachments:
            if isinstance(item, dict):
                raw.append(f"Document link: {cls.text(item.get('Description'))} {item.get('Url') or ''}")
        if signals := procurement_product_signals(record.get("Items") or []):
            raw.append(signals)
        return {"title": title, "agency": agency, "description": description + ("\n" + extra if extra else ""),
                "opportunity_url": f"{cls.endpoint_root}/Details/{bid_id}", "state": "MS",
                "county": county[1] if county else None,
                "city": city[1] if city else None,
                "posted_date": cls.source_date(record.get("AdvertiseDate")),
                "due_date": cls.source_date(record.get("SubmissionDate")),
                "contact_name": contact_name,
                "contact_email": contact_email,
                "contact_phone": cls.text(record.get("BuyerPhone")) or None,
                "solicitation_number": str(record.get("ObjectID") or record.get("BidNumber") or f"{cls.slug}:{bid_id}"),
                "procurement_type": procurement, "engineering_required": True if engineering else None,
                "professional_services": True if professional else None, "raw_text": "\n".join(raw)}

    def parse(self, content: str) -> list[dict]:
        records = self.decode(content).get("records")
        if not isinstance(records, list):
            raise ScraperError("Missing collected detail records")
        parsed = []
        for record in records:
            try:
                if not isinstance(record, dict):
                    raise ValueError("Invalid detail record")
                if self.is_relevant(record):
                    parsed.append(self.parse_detail(record))
                else:
                    self.metrics["records_excluded_relevance"] = self.metrics.get("records_excluded_relevance", 0) + 1
            except (ValueError, TypeError, OverflowError, OSError) as exc:
                self.warn_record(record.get("BidID") if isinstance(record, dict) else "unknown", exc)
        self.metrics["records_parsed"] = len(parsed)
        return parsed

    def normalize(self, records: list[dict]) -> list[OpportunityInput]:
        normalized = []
        for record in records:
            try:
                normalized.extend(super().normalize([record]))
            except (ValidationError, ValueError) as exc:
                self.warn_record(record.get("solicitation_number", "unknown"), exc)
        self.metrics["records_normalized"] = len(normalized)
        return normalized
