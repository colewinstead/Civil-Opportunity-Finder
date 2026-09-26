"""Offline integration coverage using saved public portal responses."""
import copy
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import func, select

from app.models import CollectionRun, Opportunity, Source
from app.models.opportunity import Category, Status
from app.scrapers.base import PoliteHTTPClient, ScraperError
from app.scrapers.mississippi_procurement import MississippiProcurementScraper as Scraper
from app.scrapers.registry import SCRAPERS, sync_sources
from app.services.classifier import classify
from app.services.collection import CollectionService
from app.services.scoring import score_match

FIXTURES = Path(__file__).parent / "fixtures" / "mississippi_procurement"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def detail(bid=46558):
    return fixture(f"detail_{bid}.json")


def envelope(*records):
    return json.dumps({"records": records})


def test_registry_and_metadata():
    assert SCRAPERS[Scraper.slug] is Scraper
    assert Scraper.default_active and not Scraper.is_demo
    assert Scraper.source_url.startswith("https://www.ms.gov/")


def test_saved_listing_pages():
    first, total = Scraper.parse_listing_page(json.dumps(fixture("listing_page_1.json")))
    second, second_total = Scraper.parse_listing_page(json.dumps(fixture("listing_page_2.json")))
    assert len(first) == 100 and len(second) == 29 and total == second_total == 129
    assert len({row["BidID"] for row in first + second}) == total
    assert first[0]["BidID"] == 38017
    example = next(row for row in first + second if row["BidID"] == 46558)
    assert example["Agency"] == "MPTAP" and example["ObjectID"] == "3170036622"
    assert example["BidNumber"] == "171-20260831151620 CCEDD"
    assert all(first[i]["BidID"] < first[i+1]["BidID"] for i in range(len(first)-1))


def test_detail_fields_and_normalization(settings):
    scraper = Scraper(settings)
    record = scraper.normalize(scraper.parse(envelope(detail())))[0]
    assert record.agency == "Choctaw County Economic Development District"
    assert record.solicitation_number == "3170036622"
    assert record.opportunity_url == Scraper.endpoint_root + "/Details/46558"
    assert record.county == "Choctaw" and record.city is None and record.state == "MS"
    assert record.posted_date == date(2026, 9, 23)
    assert record.due_date == date(2026, 10, 5)
    assert record.contact_email == "pbenson@gtpdd.com"
    assert record.contact_name == "phylis benson"
    assert record.contact_phone is None and record.estimated_value is None
    assert record.procurement_type == "RFQ"
    assert record.professional_services and record.engineering_required
    assert "SubmissionTime: 10:00:00" in record.raw_text
    assert "IGNITE Engineering Services RFQ Notice.pdf" in record.raw_text
    assert "171-20260831151620 CCEDD" in record.raw_text
    assert "ExtensionData" not in record.description


def test_lee_county_detail(settings):
    record = Scraper(settings).normalize([Scraper.parse_detail(detail(46604))])[0]
    assert record.agency == "Lee County" and record.county == "Lee"
    assert record.procurement_type == "RFP" and record.professional_services is True
    assert record.due_date == date(2026, 10, 1)
    assert record.posted_date == date(2026, 9, 25)
    assert record.contact_email == "sbishop@trpdd.com"
    assert "SubmissionTime: 17:00:00" in record.raw_text


def test_classification_scoring_of_real_records(settings):
    scraper = Scraper(settings)
    site, sewer = scraper.normalize(scraper.parse(envelope(detail(), detail(46562))))
    site_category, _ = classify(site.description)
    sewer_category, _ = classify(sewer.description)
    assert site_category == Category.SITE_DEVELOPMENT
    assert sewer_category == Category.WATER_SEWER
    site_score = score_match(site.model_dump(), site_category)
    unrelated = score_match({"title": "Medical supplies only", "state": "MS"}, Category.OTHER)
    assert 70 <= site_score < 100 and site_score > unrelated + 40


def test_explicit_construction_issuer_is_not_publisher_address():
    record = Scraper.parse_detail(detail(46562))
    assert record["agency"] == "Town of North Carrollton"
    assert record["city"] == "North Carrollton" and record["county"] is None


@pytest.mark.parametrize("description,agency,county,city", [
    ("Bids will be received by the Board of Supervisors of Jasper County in Bay Springs, Mississippi.",
     "Board of Supervisors of Jasper County", "Jasper", None),
    ("Sealed bids will be received by the City of Greenwood in the Office of the Mayor.",
     "City of Greenwood", None, "Greenwood"),
    ("Bids received by Pearlington Water and Sewer District, at the office.",
     "Pearlington Water and Sewer District", None, None),
])
def test_explicit_issuer_patterns(description, agency, county, city):
    payload = detail()
    payload["BidDescription"] = description
    record = Scraper.parse_detail(payload)
    assert (record["agency"], record["county"], record["city"]) == (agency, county, city)


@pytest.mark.parametrize("text,category", [
    ("industrial site infrastructure study", Category.SITE_DEVELOPMENT),
    ("site suitability assessments", Category.SITE_DEVELOPMENT),
    ("water well rehabilitation", Category.WATER_SEWER),
])
def test_general_keyword_gaps(text, category):
    assert classify(text)[0] == category


@pytest.mark.parametrize("value,expected", [
    (None, None), ("", None), ("/Date(1791176400000)/", date(2026, 10, 5)),
    ("/Date(1767247200000)/", date(2026, 1, 1)),
    ("2026-10-05T17:00:00-05:00", date(2026, 10, 5)),
    ("2026-10-05T22:00:00Z", date(2026, 10, 5)),
    ("10/05/2026", date(2026, 10, 5)),
    ("10/05/2026 5:00 PM", date(2026, 10, 5)),
    ("10/05/2026 5:00:00 PM", date(2026, 10, 5)),
])
def test_source_date_formats(value, expected):
    assert Scraper.source_date(value) == expected


def test_missing_fields_and_escaped_html(settings):
    payload = detail()
    for key in ("AdvertiseDate", "SubmissionDate", "BuyerName", "BuyerEmail", "BuyerPhone", "Attachments", "Items", "AdditionalInfo"):
        payload.pop(key, None)
    payload["BidDescription"] = "<b>Engineering services RFQ</b> &amp; drainage"
    payload["Agency"] = "MPTAP"
    record = Scraper(settings).normalize([Scraper.parse_detail(payload)])[0]
    assert record.posted_date is record.due_date is None
    assert record.contact_email is None
    assert record.agency == "MPTAP" and record.city is None and record.county is None
    assert record.description == "Engineering services RFQ & drainage"


@pytest.mark.parametrize("content", ["<html>error</html>", "[]", "{}", '{"aaData":[],"iTotalDisplayRecords":"bad"}'])
def test_malformed_listing(content):
    with pytest.raises(ScraperError):
        Scraper.parse_listing_page(content)


def test_individual_malformed_record_does_not_discard_good_record(settings):
    scraper = Scraper(settings)
    broken = detail(46604)
    broken["SubmissionDate"] = "not a date"
    records = scraper.normalize(scraper.parse(envelope(broken, detail())))
    assert len(records) == 1 and records[0].solicitation_number == "3170036622"
    assert "Malformed source date" in scraper.record_errors[0]


def test_invalid_normalized_record_visible(settings):
    scraper = Scraper(settings)
    records = scraper.normalize([{"title": "", "opportunity_url": "javascript:alert(1)"}, Scraper.parse_detail(detail())])
    assert len(records) == 1 and len(scraper.record_errors) == 1


def mock_http(settings, *, failure=None, duplicate=False, changed_total=False, no_progress=False):
    calls = []
    pages = [fixture("listing_page_1.json"), fixture("listing_page_2.json")]
    rows = {row["BidID"]: row for page in pages for row in page["aaData"]}
    def handle(request):
        calls.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
        if request.method == "POST":
            form = parse_qs(request.content.decode())
            assert form["iSortCol_0"] == ["8"] and form["sSortDir_0"] == ["asc"]
            index = int(form["iDisplayStart"][0]) // 100
            payload = copy.deepcopy(pages[index])
            if index and duplicate:
                payload["aaData"][0] = pages[0]["aaData"][0]
            if index and changed_total:
                payload["iTotalDisplayRecords"] += 1
            if index and no_progress:
                payload["aaData"] = []
            return httpx.Response(200, json=payload)
        bid = int(request.url.path.rsplit("/", 1)[1])
        if bid == 46558 and failure:
            if failure == "timeout":
                raise httpx.ReadTimeout("Detail timed out", request=request)
            if failure == "http":
                return httpx.Response(404)
            if failure == "denied":
                return httpx.Response(403)
            if failure == "json":
                return httpx.Response(200, text="not JSON")
            if failure == "identifier":
                return httpx.Response(200, json={"BidID": 99})
        payload = detail(bid) if bid in (46558, 46604, 46562) else rows[bid]
        return httpx.Response(200, json=payload)
    return PoliteHTTPClient(settings, httpx.MockTransport(handle)), calls


def test_fetches_every_page_and_paces_details(settings):
    http, calls = mock_http(settings)
    try:
        scraper = Scraper(settings, http)
        records = scraper.run()
        assert scraper.metrics["pages_fetched"] == 2
        assert scraper.metrics["records_discovered"] == 129
        assert scraper.metrics["detail_requests"] == sum(Scraper.is_candidate(row) for number in (1, 2)
                                                        for row in fixture(f"listing_page_{number}.json")["aaData"])
        assert any(record.solicitation_number == "3170036622" for record in records)
        assert any(record.solicitation_number == "3170036664" for record in records)
        assert not scraper.record_errors
        assert all(request.headers["user-agent"] == settings.scraper_user_agent for request in calls)
    finally:
        http.close()


@pytest.mark.parametrize("failure", ["timeout", "http", "json", "identifier"])
def test_detail_failure_is_visible_and_other_records_continue(settings, failure):
    http, _ = mock_http(settings, failure=failure)
    try:
        scraper = Scraper(settings, http)
        records = scraper.run()
        assert any(record.solicitation_number == "3170036664" for record in records)
        assert not any(record.solicitation_number == "3170036622" for record in records)
        assert len(scraper.record_errors) == 1 and "46558" in scraper.record_errors[0]
    finally:
        http.close()


@pytest.mark.parametrize("option", ["duplicate", "changed_total", "no_progress"])
def test_pagination_inconsistency_fails_visibly(settings, option):
    http, _ = mock_http(settings, **{option: True})
    try:
        with pytest.raises(ScraperError):
            Scraper(settings, http).run()
    finally:
        http.close()


def test_access_rejection_stops_detail_requests(settings):
    http, calls = mock_http(settings, failure="denied")
    try:
        with pytest.raises(ScraperError, match="access denied"):
            Scraper(settings, http).run()
        assert calls[-1].url.path.endswith("/46558")
    finally:
        http.close()


def test_consecutive_detail_failures_stop_source(settings):
    detail_requests = []
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.method == "POST":
            return httpx.Response(200, json=fixture("listing_page_1.json") | {"iTotalDisplayRecords": 100})
        detail_requests.append(request)
        return httpx.Response(500)
    http = PoliteHTTPClient(settings, httpx.MockTransport(handle))
    try:
        with pytest.raises(ScraperError, match="Three consecutive"):
            Scraper(settings, http).run()
        assert len(detail_requests) == 3
    finally:
        http.close()


def fixture_collector(sessions, settings, payloads):
    class SavedScraper(Scraper):
        def fetch(self):
            self.metrics = {"records_discovered": len(payloads)}
            return envelope(*payloads)
    registry = {Scraper.slug: SavedScraper}
    with sessions.begin() as session:
        sync_sources(session, registry)
    return CollectionService(sessions, settings, registry)


def test_repeat_and_changed_source_update_preserves_status(sessions, settings):
    payloads = [detail()]
    collector = fixture_collector(sessions, settings, payloads)
    first = collector.collect(Scraper.slug)
    with sessions.begin() as session:
        record = session.scalar(select(Opportunity))
        identifier, first_seen, last_seen, old_hash = record.id, record.first_seen, record.last_seen, record.content_hash
        record.status = Status.INTERESTED
        assert session.get(CollectionRun, first).records_added == 1
    repeat = collector.collect(Scraper.slug)
    payloads[0]["SubmissionDate"] = "/Date(1791262800000)/"
    payloads[0]["AdditionalInfo"] += " Updated due date."
    changed = collector.collect(Scraper.slug)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 1
        record = session.get(Opportunity, identifier)
        assert record.first_seen == first_seen and record.last_seen > last_seen
        assert record.status == Status.INTERESTED and record.due_date == date(2026, 10, 6)
        assert record.content_hash != old_hash and "Updated due date" in record.description
        for run_id in (repeat, changed):
            run = session.get(CollectionRun, run_id)
            assert run.records_added == 0 and run.records_updated == 1 and run.outcome == "SUCCEEDED"


def test_partial_run_persists_good_records_and_reports_errors(sessions, settings, client):
    bad = detail(46604)
    bad["SubmissionDate"] = "bad date"
    collector = fixture_collector(sessions, settings, [bad, detail()])
    run_id = collector.collect(Scraper.slug)
    with sessions() as session:
        run = session.get(CollectionRun, run_id)
        assert run.outcome == "PARTIAL" and run.records_added == 1
        assert "Malformed source date" in run.errors
        source = session.scalar(select(Source).where(Source.slug == Scraper.slug))
        assert source.last_checked and source.last_successful is None
    response = client.get(f"/api/scrape-runs/{run_id}")
    assert response.status_code == 200 and response.json()["run"]["outcome"] == "PARTIAL"
    assert "Malformed source date" in response.json()["run"]["errors"]


def test_all_malformed_is_failed_not_success(sessions, settings):
    bad = detail()
    bad["SubmissionDate"] = "bad date"
    collector = fixture_collector(sessions, settings, [bad])
    run_id = collector.collect(Scraper.slug)
    with sessions() as session:
        run = session.get(CollectionRun, run_id)
        assert run.outcome == "FAILED" and run.records_added == 0 and run.errors


def test_live_fixture_dashboard_filters_and_links(sessions, settings, client):
    fixture_collector(sessions, settings, [detail(), detail(46604)]).collect(Scraper.slug)
    response = client.get("/api/opportunities", params={"source": Scraper.source_name, "county": "Choctaw", "min_score": 70})
    assert response.status_code == 200 and response.json()["total"] == 1
    record = response.json()["items"][0]
    assert client.get("/").status_code == 200
    response = client.get(f"/opportunities/{record['id']}")
    assert response.status_code == 200 and record["opportunity_url"] in response.text


@pytest.mark.parametrize("bid,category", [
    (46460, Category.BRIDGE), (46476, Category.ROADWAY),
    (46489, Category.DRAINAGE), (46495, Category.WATER_SEWER),
    (46568, Category.UTILITIES), (46571, Category.UTILITIES), (46603, Category.UTILITIES),
])
def test_audit_missed_real_civil_records_are_retained(settings, bid, category):
    payload = detail(bid)
    scraper = Scraper(settings)
    assert Scraper.is_candidate(payload) and Scraper.is_relevant(payload)
    record = scraper.normalize(scraper.parse(envelope(payload)))[0]
    primary, secondary = classify(" ".join((record.title, record.description, record.raw_text)))
    assert category == primary or category.value in secondary
    assert record.opportunity_url.endswith(f"/Details/{bid}")


@pytest.mark.parametrize("bid", [46407, 46552])
def test_ambiguous_park_and_architectural_rfq_retained_for_review(settings, bid):
    payload = detail(bid)
    assert Scraper.is_candidate(payload) and Scraper.is_relevant(payload)
    assert len(Scraper(settings).normalize(Scraper(settings).parse(envelope(payload)))) == 1


@pytest.mark.parametrize("title", ["Professional Services", "Consulting Services", "Request for Qualifications",
                                   "Planning Services", "Infrastructure Improvements"])
def test_generic_titles_do_not_prevent_detail_review(title, settings):
    payload = detail()
    payload["BidDescription"] = title
    payload["ProcurementCategoryID"] = None
    payload["Items"] = []
    payload["Attachments"] = []
    payload["AdditionalInfo"] = "Transportation planning and stormwater consulting services."
    assert Scraper.is_candidate(payload) and Scraper.is_relevant(payload)
    record = Scraper(settings).normalize(Scraper(settings).parse(envelope(payload)))[0]
    assert record.description.startswith(title)


def test_generic_description_recovered_by_attachment_and_code():
    payload = detail()
    payload["BidDescription"] = "Request for Qualifications"
    payload["AdditionalInfo"] = None
    payload["Items"] = []
    payload["Attachments"] = [{"Description": "Transportation planning and drainage design RFQ.pdf"}]
    assert Scraper.is_relevant(payload)
    payload["Attachments"] = []
    payload["Items"] = [{"CategoryNumber": "91366", "CategoryDescription": "Serv ConsHeavMainBrd"}]
    assert Scraper.is_relevant(payload)
    payload["Items"] = [{"CategoryNumber": "91800", "CategoryDescription": "Serv Consulting"}]
    assert not Scraper.is_relevant(payload)


@pytest.mark.parametrize("bid", [38017, 46254, 46507, 46454, 46524])
def test_audit_unrelated_it_housekeeping_banking_uniforms_materials_still_excluded(bid):
    payload = detail(bid)
    assert Scraper.is_candidate(payload)  # details reviewed, not discarded on title/category
    assert not Scraper.is_relevant(payload)


@pytest.mark.parametrize("notification", ["13", "14", "15"])
def test_noncompetitive_notification_exclusion_is_explicit(notification):
    assert not Scraper.is_candidate(detail() | {"SubProcurementCategoryID": notification})


def test_audit_recovered_records_repeat_collection_preserves_status(sessions, settings):
    payloads = [detail(bid) for bid in (46460, 46476, 46489, 46495, 46568, 46571, 46603)]
    collector = fixture_collector(sessions, settings, payloads)
    first = collector.collect(Scraper.slug)
    with sessions.begin() as session:
        records = session.scalars(select(Opportunity)).all()
        assert len(records) == len(payloads)
        identifiers = {row.id for row in records}
        records[0].status = Status.REVIEWING
    second = collector.collect(Scraper.slug)
    with sessions() as session:
        assert {row.id for row in session.scalars(select(Opportunity))} == identifiers
        assert session.get(CollectionRun, first).records_added == len(payloads)
        assert session.get(CollectionRun, second).records_added == 0
        assert session.get(CollectionRun, second).records_updated == len(payloads)
        assert session.scalar(select(Opportunity.status).where(Opportunity.id == min(identifiers))) == Status.REVIEWING
