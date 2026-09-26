# Mississippi procurement fixtures

Public JSON responses captured September 26, 2026, using the portal's own
DataTables form and the existing robots-aware HTTP client. No authentication.

- `listing_page_1.json`: POST https://www.ms.gov/dfa/contract_bid_search/Bid/BidData?AppId=1&Status=Open, offset 0, length 100, ascending BidID.
- `listing_page_2.json`: same query/form, offset 100; 29 rows (129 total).
- `detail_46558.json`: GET https://www.ms.gov/dfa/contract_bid_search/Bid/BidDetailData/46558 (Choctaw County engineering RFQ).
- `detail_46604.json`: corresponding detail endpoint (Lee County engineering RFP).
- `detail_46562.json`: corresponding detail endpoint (North Carrollton sewer improvements).

These are source responses, including public notice contact information. Linked
documents have not been downloaded. Dates and identifiers are fixed offline test
data, not guarantees that these listings remain open. Tests derive changed and
malformed variants explicitly; they never contact the portal.

Additional `detail_<BidID>.json` responses were captured during the focused
September 26 coverage audit from the same public detail endpoint. They include
missed road/bridge/drainage/sewer/utility cases, a park construction notice, an
architectural RFQ, and negative examples (IT, housekeeping, banking, highway
uniforms, and road-material supplies). See the row-level IDs, provenance and
decisions in `docs/mississippi-procurement-coverage-audit.md` and its CSV.
