import pytest
from factory import readability as rd
from factory.readability import ReadabilityError


def test_count_syllables_basic():
    assert rd.count_syllables("cat") == 1
    assert rd.count_syllables("apple") == 2
    assert rd.count_syllables("banana") == 3
    assert rd.count_syllables("the") == 1          # silent-e floor keeps it at 1
    assert rd.count_syllables("") == 0


def test_simple_text_scores_easier_than_complex():
    simple = "The cat sat. The dog ran. We had fun."
    complex_ = ("Extraordinarily sophisticated metropolitan infrastructure "
                "necessitates comprehensive administrative reorganization.")
    assert rd.flesch_kincaid_grade(simple) < rd.flesch_kincaid_grade(complex_)
    assert rd.flesch_reading_ease(simple) > rd.flesch_reading_ease(complex_)


def test_empty_text_is_easiest():
    assert rd.flesch_kincaid_grade("") == 0.0
    assert rd.flesch_reading_ease("") == 100.0


def test_kids_text_collects_pages_dedication_and_closing():
    content = {"pages": [{"text": "a b"}, {"text": ""}, {"text": "c d"}],
               "dedication": "for you", "closing": "the end"}
    labels = [lbl for lbl, _ in rd.kids_text(content)]
    assert labels == ["page 1", "page 3", "dedication", "closing"]  # empty page skipped


def test_report_flags_hardest_item():
    content = {"pages": [{"text": "The cat sat on the mat."},
                         {"text": "Incomprehensible juxtapositions bewilder."}],
               "closing": "Bye."}
    rep = rd.readability_report(content)
    assert rep["hardest"]["where"] == "page 2"
    assert rep["grade"] > 0


def test_verify_readability_raises_when_over_ceiling():
    content = {"pages": [{"text": ("Extraordinarily sophisticated infrastructure "
                                   "necessitates reorganization continuously.")}]}
    with pytest.raises(ReadabilityError):
        rd.verify_readability(content, max_grade=4.0)


def test_verify_readability_passes_simple_kids_text():
    content = {"pages": [{"text": "The fox is red.\nIt likes to play."},
                         {"text": "A bee can buzz.\nA bird can sing."}],
               "dedication": "For all kids.", "closing": "The end."}
    rep = rd.verify_readability(content, max_grade=6.0)   # must not raise
    assert rep["grade"] <= 6.0


def test_verify_readability_disabled_with_zero_ceiling():
    content = {"pages": [{"text": ("Extraordinarily sophisticated infrastructure "
                                   "necessitates reorganization.")}]}
    rep = rd.verify_readability(content, max_grade=0)     # disabled → never raises
    assert "grade" in rep
