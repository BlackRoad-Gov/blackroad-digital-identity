"""Tests for digital_identity.py"""
import pytest
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Use a temp DB
os.environ["TESTING"] = "1"
import digital_identity as di
di.DB_PATH = Path("/tmp/test_digital_identity.db")


@pytest.fixture(autouse=True)
def clean_db():
    if di.DB_PATH.exists():
        di.DB_PATH.unlink()
    di.init_db()
    yield
    if di.DB_PATH.exists():
        di.DB_PATH.unlink()


def test_create_identity():
    identity = di.create_identity("Alice Smith", "alice@example.com")
    assert identity.holder_name == "Alice Smith"
    assert identity.holder_email == "alice@example.com"
    assert identity.verification_level == di.VerificationLevel.UNVERIFIED
    assert identity.status == di.IdentityStatus.ACTIVE


def test_submit_document():
    identity = di.create_identity("Bob Jones", "bob@example.com")
    doc = di.submit_document(
        identity.identity_id,
        di.DocType.PASSPORT,
        "P123456",
        "US",
        "2030-01-01"
    )
    assert doc.doc_type == di.DocType.PASSPORT
    assert doc.verified is False


def test_verify_document():
    identity = di.create_identity("Carol White", "carol@example.com")
    doc = di.submit_document(identity.identity_id, di.DocType.LICENSE, "DL789", "CA", "2028-06-01")
    result = di.verify_document(identity.identity_id, doc.doc_id)
    assert result is True
    docs = di.get_documents(identity.identity_id)
    assert docs[0]["verified"] == 1


def test_kyc_process():
    identity = di.create_identity("Dave Brown", "dave@example.com")
    doc = di.submit_document(identity.identity_id, di.DocType.PASSPORT, "P999", "UK", "2029-01-01")
    di.verify_document(identity.identity_id, doc.doc_id)
    req = di.initiate_kyc(identity.identity_id, di.VerificationLevel.BASIC)
    assert req.status == di.KYCStatus.PENDING
    processed = di.process_kyc(req.request_id)
    assert processed.status == di.KYCStatus.APPROVED


def test_revoke_identity():
    identity = di.create_identity("Eve Black", "eve@example.com")
    result = di.revoke_identity(identity.identity_id, "Fraudulent activity")
    assert result is True
    info = di.check_verification_level(identity.identity_id)
    assert info["status"] == di.IdentityStatus.REVOKED.value


def test_identity_stats():
    di.create_identity("Frank Green", "frank@example.com")
    di.create_identity("Grace Hall", "grace@example.com")
    stats = di.identity_stats()
    assert stats["total_identities"] >= 2
    assert "by_verification_level" in stats


def test_search_identity():
    di.create_identity("Helen Troy", "helen@example.com")
    results = di.search_identity("Helen")
    assert len(results) >= 1
    assert results[0]["holder_name"] == "Helen Troy"


def test_suspend_and_reactivate():
    identity = di.create_identity("Ivan Drago", "ivan@example.com")
    di.suspend_identity(identity.identity_id, "Under review")
    info = di.check_verification_level(identity.identity_id)
    assert info["status"] == di.IdentityStatus.SUSPENDED.value
    di.reactivate_identity(identity.identity_id)
    info2 = di.check_verification_level(identity.identity_id)
    assert info2["status"] == di.IdentityStatus.ACTIVE.value


def test_audit_trail():
    identity = di.create_identity("Julia Roberts", "julia@example.com")
    di.submit_document(identity.identity_id, di.DocType.NATIONAL_ID, "NID001", "DE", "2031-01-01")
    audit = di.get_audit_trail(identity.identity_id)
    assert len(audit) >= 2
    actions = [a["action"] for a in audit]
    assert "CREATE_IDENTITY" in actions
    assert "SUBMIT_DOCUMENT" in actions


def test_generate_report():
    identity = di.create_identity("Karl Marx", "karl@example.com")
    report = di.generate_identity_report(identity.identity_id)
    assert "DIGITAL IDENTITY REPORT" in report
    assert "Karl Marx" in report
