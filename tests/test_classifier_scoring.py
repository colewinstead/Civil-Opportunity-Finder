import pytest

from app.models.opportunity import Category
from app.services.classifier import KEYWORDS, classify
from app.services.scoring import score_match


@pytest.mark.parametrize("category,phrase", [(category, phrases[0]) for category, phrases in KEYWORDS.items()])
def test_every_category(category, phrase):
    assert classify(phrase)[0] == category


def test_unknown_and_phrase_boundaries():
    assert classify("Office supplies")[0] == Category.OTHER
    assert classify("structural architecture")[0] == Category.OTHER
    assert classify("surveying")[0] == Category.SURVEY


def test_multi_category_and_tie_order():
    category, additional = classify("roadway drainage")
    assert category == Category.ROADWAY
    assert additional == [Category.DRAINAGE.value]
    assert classify("roadway drainage stormwater")[0] == Category.DRAINAGE


def test_professional_opportunity_ranks_above_commodity(item):
    assert score_match(item.model_dump(), Category.ROADWAY) == 100
    assert score_match({"title": "Office supplies only", "state": "MS"}, Category.OTHER) == 0


@pytest.mark.parametrize("factor,values", [
    ("civil", {"title": "civil engineering"}),
    ("professional", {"professional_services": True}),
    ("rfq_rfp", {"procurement_type": "RFQ"}),
    ("consulting", {"title": "consulting"}),
    ("design", {"title": "design"}),
    ("mississippi", {"state": "MS"}),
])
def test_individual_score_signals(factor, values):
    weights = {key: 0 for key in ("civil", "professional", "rfq_rfp", "consulting", "design", "mississippi", "discipline", "unrelated")}
    weights[factor] = 17
    assert score_match(values, Category.OTHER, weights) == 17


@pytest.mark.parametrize("phrase", ["supplies only", "equipment purchase", "janitorial", "IT services", "medical"])
def test_unrelated_penalties(phrase):
    values = {"title": "Professional engineering services design RFQ " + phrase, "state": "MS"}
    assert score_match(values, Category.ROADWAY) < score_match(values | {"title": "Professional engineering services design RFQ"}, Category.ROADWAY)


def test_bounds_and_custom_weights():
    assert score_match({"title": "design"}, Category.ROADWAY, {"design": 500}) == 100
    assert score_match({"title": "design"}, Category.OTHER, {"design": -500}) == 0
