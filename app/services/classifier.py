"""Transparent phrase classification; dictionary insertion order breaks ties."""
import re

from app.models.opportunity import Category

KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.ROADWAY: ("roadway", "road improvements", "highway", "intersection", "traffic", "pavement", "streetscape", "transportation improvements", "road paving", "road resurfacing", "road construction", "street paving", "asphalt overlay", "striping", "pedestrian lighting"),
    Category.SITE_DEVELOPMENT: ("site development", "parking", "grading", "commercial development", "industrial development", "industrial site", "site suitability"),
    Category.DRAINAGE: ("drainage", "stormwater", "culvert", "detention", "watershed", "flood", "hydraulic", "hydrologic", "erosion control", "bank stabilization", "storm drain"),
    Category.WATER_SEWER: ("water main", "sewer", "wastewater", "lift station", "treatment plant", "force main", "water well", "pump station", "lagoon upgrades", "water tank"),
    Category.SURVEY: ("surveying", "boundary survey", "topographic survey", "right-of-way survey"),
    Category.BRIDGE: ("bridge", "bridge replacement", "bridge inspection"),
    Category.TRANSPORTATION_PLANNING: ("transportation planning", "long range transportation", "mobility plan", "traffic study", "travel demand"),
    Category.CEI: ("construction engineering", "construction inspection", "CE&I", "construction administration"),
    Category.MUNICIPAL: ("municipal engineering", "city engineer", "municipal infrastructure", "town engineer"),
    Category.LAND_DEVELOPMENT: ("land development", "subdivision", "platting", "land use"),
    Category.UTILITIES: ("utility infrastructure", "utility relocation", "utilities", "utility design", "electric distribution", "utility location", "utility locating"),
}

# Civil service codes, not material/equipment codes. Meanings checked against
# public government NIGP listings; see the coverage audit in docs/.
NIGP_CIVIL_SIGNALS = {
    **dict.fromkeys(("91310", "91327", "91350", "91364", "91371", "91384", "91395", "91396", "91232", "91276"), "roadway"),
    **dict.fromkeys(("91313", "91366", "91367"), "bridge"),
    **dict.fromkeys(("91319", "91339", "91377"), "drainage"),
    **dict.fromkeys(("91345", "91359", "91360", "91381", "91391", "91392"), "water/sewer"),
    **dict.fromkeys(("91336", "91347", "91375", "91382", "91394", "90976", "91244"), "site development"),
    **dict.fromkeys(("91356", "91389", "96878"), "utility infrastructure"),
}


def procurement_product_signals(items: list[dict]) -> str:
    """Expose supported civil service codes to the same keyword classifier.

    Keep original codes/abbreviated descriptions in source raw text. These
    explicit signals supplement truncated descriptions, rather than inferring
    relevance from any generic construction/consulting code.
    """
    signals = []
    for item in items:
        if isinstance(item, dict):
            code = str(item.get("CategoryNumber", ""))
            if signal := NIGP_CIVIL_SIGNALS.get(code):
                signals.append(f"NIGP civil discipline {code}: {signal}")
    return "\n".join(signals)


def contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE))


def classify(text: str, keywords: dict = KEYWORDS) -> tuple[Category, list[str]]:
    """Count distinct matched phrases, then rank by count and configured order."""
    matches = [(Category(category), sum(contains_phrase(text, phrase) for phrase in phrases))
               for category, phrases in keywords.items()]
    ranked = sorted((item for item in matches if item[1]), key=lambda item: -item[1])
    if not ranked:
        return Category.OTHER, []
    return ranked[0][0], [item[0].value for item in ranked[1:]]
