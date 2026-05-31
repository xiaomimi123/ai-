"""内部制度刚性规则单元测试。"""
from app.parsers.txt_parser import parse_text_content
from app.rules.institution import (
    ApprovalRule,
    BasisRule,
    DocumentNumberRule,
    EffectiveDateRule,
    INSTITUTION_RIGID_RULES,
    RequiredSectionsRule,
)
from tests.samples import BAD_INSTITUTION, GOOD_INSTITUTION


def _doc(text):
    return parse_text_content(text, file_name="institution.txt")


def test_good_institution_passes_all_rigid():
    issues = []
    for rule in INSTITUTION_RIGID_RULES:
        issues.extend(rule.check(_doc(GOOD_INSTITUTION)))
    assert issues == [], [i.description for i in issues]


def test_bad_institution_missing_doc_number():
    assert len(DocumentNumberRule().check(_doc(BAD_INSTITUTION))) == 1


def test_good_institution_doc_number_present():
    assert DocumentNumberRule().check(_doc(GOOD_INSTITUTION)) == []


def test_bad_institution_missing_effective_date():
    assert len(EffectiveDateRule().check(_doc(BAD_INSTITUTION))) == 1


def test_bad_institution_missing_basis():
    assert len(BasisRule().check(_doc(BAD_INSTITUTION))) == 1


def test_bad_institution_missing_sections():
    issues = RequiredSectionsRule().check(_doc(BAD_INSTITUTION))
    descs = " ".join(i.description for i in issues)
    assert "总则" in descs and "附则" in descs


def test_bad_institution_missing_approval():
    assert len(ApprovalRule().check(_doc(BAD_INSTITUTION))) == 1
