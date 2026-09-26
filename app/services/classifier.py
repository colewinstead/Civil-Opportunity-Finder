"""Transparent phrase classification; dictionary insertion order breaks ties."""
import re

from app.models.opportunity import Category

KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.ROADWAY: ("roadway", "road improvements", "highway", "intersection", "traffic", "pavement", "streetscape", "transportation improvements"),
    Category.SITE_DEVELOPMENT: ("site development", "parking", "grading", "commercial development", "industrial development"),
    Category.DRAINAGE: ("drainage", "stormwater", "culvert", "detention", "watershed", "flood", "hydraulic", "hydrologic"),
    Category.WATER_SEWER: ("water main", "sewer", "wastewater", "lift station", "treatment plant", "force main"),
    Category.SURVEY: ("surveying", "boundary survey", "topographic survey", "right-of-way survey"),
    Category.BRIDGE: ("bridge", "bridge replacement", "bridge inspection"),
    Category.TRANSPORTATION_PLANNING: ("transportation planning", "long range transportation", "mobility plan", "traffic study", "travel demand"),
    Category.CEI: ("construction engineering", "construction inspection", "CE&I", "construction administration"),
    Category.MUNICIPAL: ("municipal engineering", "city engineer", "municipal infrastructure", "town engineer"),
    Category.LAND_DEVELOPMENT: ("land development", "subdivision", "platting", "land use"),
    Category.UTILITIES: ("utility infrastructure", "utility relocation", "utilities", "utility design", "electric distribution"),
}


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
