# Mississippi procurement coverage audit — September 26, 2026

This focused follow-up reviewed both listing pages and retrieved all **129 public
detail JSON responses** using the existing robots-aware, paced HTTP client.
It did not download PDFs, add sources, alter storage, or enable the scheduler.
The [row-by-row audit](mississippi-procurement-coverage-audit.csv) records each
ID, original exclusion stage, corrected decision, supplied descriptions/codes,
attachment names, and original URL. These are dated results, not future counts.

## Original reduction

| Stage | Count | Decision |
| --- | ---: | --- |
| Discovered across two listing pages | 129 | All open search results |
| Excluded before detail retrieval | 40 | 26 COMMODITIES, 13 IT, 1 personnel notice with excluded notification code |
| Details retrieved | 89 | Only personnel/construction major categories, excluding notification codes 13–15 |
| Excluded after details | 77 | No keyword category, NIGP 925 engineering product, or explicit engineering/surveying service phrase in description/additional information |
| Parsed and normalized | 12 | No malformed-record or validation losses |

Before-detail exclusions were in `fetch()` via `is_candidate()`. After-detail
exclusions were in `parse()` via `is_relevant()`. Collection persistence,
deduplication, scoring, dashboard filters, and normalization did not discard the
117 records. The current audit reconstructed the original rules and reproduced
the same 40/77/12 counts.

## Genuine gaps and correction

- **46476, Attala County road paving:** missing road-paving phrase.
- **46460, Kemper County bridge work:** scope beyond the short description;
  detail code 91366 identified bridge maintenance.
- **46489, Warren County erosion control:** missing erosion-control phrase.
- **46495, Carthage pump station/lagoon upgrades:** missing vocabulary and code 91381.
- **46551, Richland bank stabilization:** missing bank-stabilization phrase.
- **46568, Canton Municipal Utilities:** major category COMMODITIES, but detail
  subtype CONSTRUCTION SERVICES and code 91356 (utility construction).
- **46603, underground utility location:** missing utility-location phrase.

The filter now retrieves details regardless of the major category before
deciding relevance. Only explicit notification subtypes 13–15 are skipped
before details. In this snapshot those are eight sole-source notices and one
record coded PROTECTIVE ORDER REQUEST NOTICE (its title says intent to award).

Relevance examines description, additional information, attachment names,
existing engineering codes, and a small shared dictionary of verified civil
service codes. Missing civil phrases were added to the existing classifier.
Civil discipline signals are preserved in raw text, together with original
codes and labels, so the existing classifier/scoring pipeline sees the same
evidence. IT/commodity records need explicit civil-service evidence; incidental
"highway" in uniforms or aggregates alone does not qualify.

Architectural RFQs and construction notices indicating parks, water tanks or
well pumps are retained as **potential** opportunities needing original-scope
review, not claims of proven engineering work. Generic construction/consulting
codes alone still do not qualify. No probabilities or forced high scores added.

## Representative exclusions checked

| ID | Supplied evidence | Why still excluded |
| --- | --- | --- |
| 38017 | Information Systems Consulting, code 91871 | IT consulting, not civil planning |
| 46254 | Housekeeping services; housekeeping RFP attachment | Unrelated services |
| 46366 | Non-emergency medical transportation | Patient transport, not transportation planning |
| 46454 | Highway Patrol shirts and trousers | Uniform purchase, not highway work |
| 46493 | Compensation-related consulting, generic code 91800 | HR consulting, no civil scope indicated |
| 46507 | Banking services attachment | Banking despite generic listing description |
| 46524 | Crushed road materials, code 75035, COMMODITIES | Material supply, not engineering/construction services |
| 46539 | LiDAR software maintenance, sole-source subtype | Noncompetitive software notice, not survey services |
| 46591 | Grant preparer/administrator, code 94652 | Grant administration, not engineering RFQ |

All available structured details were reviewed, exceeding the requested sample.
Some remaining generic building/renovation records may contain civil subcontract
work only described in PDFs. Their full scopes were not reviewed. No claim of
exhaustive coverage is possible without document parsing; this limitation remains
explicit rather than assuming absent keywords prove absence of civil work.

## Generic titles and unattended operation

Professional Services, Consulting Services, Request for Qualifications, Planning
Services, and Infrastructure Improvements do not fail a title test: there is no
title gate. Before correction, an incorrect/unknown major category could prevent
detail review. After correction, eligible notification types receive detail review
even with a missing category. Civil metadata or attachment names can establish
relevance despite a generic description. A completely generic JSON record whose
scope appears only in a PDF can still be missed.

The corrected strategy is suitable for best-effort daily MVP collection with
periodic exclusion audits; it is not a guarantee of comprehensive opportunity
coverage. It requests 120 details in this snapshot instead of 89, respecting the
existing two-second minimum pacing, robots checks and failure controls. New log
counters separate listing exclusions from relevance exclusions. **Scheduling
remains disabled.**

## Corrected verification

- Discovered: **129**.
- Normalized: **40**, comprising the original 12 plus **28 additional relevant
  or potentially relevant notices**.
- Excluded: **89** — 9 noncompetitive notification records before details,
  80 records without sufficient civil-service evidence after details.
- Parsing/normalization errors: **0**.
- Full offline suite: **161 passed, zero failed** (all 88 original tests retained).
- Captured live responses replayed twice through the existing BaseScraper and
  CollectionService against the default database: first added 28/refreshed 12;
  second added **0**/refreshed **40**. This was a captured-response replay, not
  two additional live network runs. Database count remained 40, IDs and original
  `first_seen`/statuses were preserved, `last_seen` advanced, and URL/solicitation
  duplicate groups were empty. The existing `INTERESTED` record remained intact.

## Service-code references

Civil code meanings were checked against government NIGP listings, rather than
interpreting opaque abbreviations as ordinary keywords:

- [Baton Rouge heavy construction codes](https://city.brla.gov/dept/purchase/NIGPcode_munis_child.asp?parent=913)
- [Baton Rouge public works codes](https://city.brla.gov/dept/purchase/NIGPcode_munis_child.asp?parent=968)
- [Michigan design/construction codes](https://www.michigan.gov/dtmb/procurement/design-and-construction/pro-and-construction-contractors/nigp-codes-for-design-and-construction-contract-solicitations)
- [Fort Worth NIGP listing](https://www.fortworthtexas.gov/files/assets/public/v/1/finance/documents/purchasing/nigp-codes.pdf)

Codes for supplies/equipment are not generally treated as civil-service codes.
