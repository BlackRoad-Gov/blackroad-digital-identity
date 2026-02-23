#!/usr/bin/env python3
"""
BlackRoad Digital Identity — Digital identity verification and KYC system
"""

import sqlite3
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from enum import Enum
from pathlib import Path


DB_PATH = Path("digital_identity.db")


class VerificationLevel(str, Enum):
    UNVERIFIED = "unverified"
    BASIC = "basic"
    STANDARD = "standard"
    ENHANCED = "enhanced"


class DocType(str, Enum):
    PASSPORT = "passport"
    LICENSE = "license"
    NATIONAL_ID = "national_id"
    UTILITY_BILL = "utility_bill"


class KYCStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"


class IdentityStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


@dataclass
class Document:
    doc_type: DocType
    number: str
    issuing_country: str
    expiry: str
    verified: bool = False
    verified_at: Optional[str] = None
    doc_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self):
        return asdict(self)


@dataclass
class Identity:
    holder_name: str
    holder_email: str
    documents: List[Document] = field(default_factory=list)
    biometric_hash: Optional[str] = None
    verification_level: VerificationLevel = VerificationLevel.UNVERIFIED
    status: IdentityStatus = IdentityStatus.ACTIVE
    issued_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: str = field(default_factory=lambda: (datetime.utcnow() + timedelta(days=365*5)).isoformat())
    identity_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class KYCRequest:
    identity_id: str
    requested_level: VerificationLevel
    documents_submitted: List[str] = field(default_factory=list)
    status: KYCStatus = KYCStatus.PENDING
    notes: str = ""
    processed_at: Optional[str] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self):
        return asdict(self)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema."""
    conn = get_connection()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS identities (
            identity_id     TEXT PRIMARY KEY,
            holder_name     TEXT NOT NULL,
            holder_email    TEXT UNIQUE NOT NULL,
            biometric_hash  TEXT,
            verification_level TEXT DEFAULT 'unverified',
            status          TEXT DEFAULT 'active',
            issued_at       TEXT NOT NULL,
            expires_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            doc_id          TEXT PRIMARY KEY,
            identity_id     TEXT NOT NULL,
            doc_type        TEXT NOT NULL,
            number          TEXT NOT NULL,
            issuing_country TEXT NOT NULL,
            expiry          TEXT NOT NULL,
            verified        INTEGER DEFAULT 0,
            verified_at     TEXT,
            FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
        );

        CREATE TABLE IF NOT EXISTS kyc_requests (
            request_id      TEXT PRIMARY KEY,
            identity_id     TEXT NOT NULL,
            requested_level TEXT NOT NULL,
            documents_submitted TEXT DEFAULT '[]',
            status          TEXT DEFAULT 'pending',
            notes           TEXT DEFAULT '',
            processed_at    TEXT,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            log_id      TEXT PRIMARY KEY,
            identity_id TEXT,
            action      TEXT NOT NULL,
            details     TEXT,
            timestamp   TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def _log_action(identity_id: str, action: str, details: str = ""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO audit_log VALUES (?,?,?,?,?)",
        (str(uuid.uuid4()), identity_id, action, details, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def create_identity(name: str, email: str, biometric_data: Optional[str] = None) -> Identity:
    """Create a new digital identity."""
    init_db()
    biometric_hash = hashlib.sha256(biometric_data.encode()).hexdigest() if biometric_data else None
    identity = Identity(holder_name=name, holder_email=email, biometric_hash=biometric_hash)
    conn = get_connection()
    conn.execute(
        "INSERT INTO identities VALUES (?,?,?,?,?,?,?,?)",
        (identity.identity_id, name, email, biometric_hash,
         identity.verification_level.value, identity.status.value,
         identity.issued_at, identity.expires_at)
    )
    conn.commit()
    conn.close()
    _log_action(identity.identity_id, "CREATE_IDENTITY", f"Created identity for {email}")
    return identity


def submit_document(identity_id: str, doc_type: DocType, number: str,
                    country: str, expiry: str) -> Document:
    """Submit a document for an identity."""
    doc = Document(doc_type=doc_type, number=number, issuing_country=country, expiry=expiry)
    conn = get_connection()
    row = conn.execute("SELECT identity_id FROM identities WHERE identity_id=?", (identity_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Identity {identity_id} not found")
    conn.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
        (doc.doc_id, identity_id, doc_type.value if isinstance(doc_type, DocType) else doc_type,
         number, country, expiry, 0, None)
    )
    conn.commit()
    conn.close()
    _log_action(identity_id, "SUBMIT_DOCUMENT", f"Submitted {doc_type} document")
    return doc


def verify_document(identity_id: str, doc_id: str) -> bool:
    """Verify a submitted document."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM documents WHERE doc_id=? AND identity_id=?",
        (doc_id, identity_id)
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Document {doc_id} not found for identity {identity_id}")
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE documents SET verified=1, verified_at=? WHERE doc_id=?",
        (now, doc_id)
    )
    conn.commit()
    conn.close()
    _log_action(identity_id, "VERIFY_DOCUMENT", f"Document {doc_id} verified")
    return True


def initiate_kyc(identity_id: str, requested_level: VerificationLevel) -> KYCRequest:
    """Initiate a KYC request for an identity."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM identities WHERE identity_id=?", (identity_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Identity {identity_id} not found")
    docs = conn.execute(
        "SELECT doc_id FROM documents WHERE identity_id=? AND verified=1",
        (identity_id,)
    ).fetchall()
    doc_ids = [d["doc_id"] for d in docs]
    req = KYCRequest(
        identity_id=identity_id,
        requested_level=requested_level,
        documents_submitted=doc_ids
    )
    conn.execute(
        "INSERT INTO kyc_requests VALUES (?,?,?,?,?,?,?,?)",
        (req.request_id, identity_id, requested_level.value if isinstance(requested_level, VerificationLevel) else requested_level,
         json.dumps(doc_ids), req.status.value, req.notes, req.processed_at, req.created_at)
    )
    conn.commit()
    conn.close()
    _log_action(identity_id, "INITIATE_KYC", f"KYC requested for level {requested_level}")
    return req


def process_kyc(request_id: str) -> KYCRequest:
    """Process a pending KYC request."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM kyc_requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"KYC request {request_id} not found")
    if row["status"] != KYCStatus.PENDING.value:
        conn.close()
        raise ValueError(f"KYC request {request_id} is not in pending state")
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE kyc_requests SET status=?, processed_at=? WHERE request_id=?",
        (KYCStatus.PROCESSING.value, now, request_id)
    )
    conn.commit()

    doc_ids = json.loads(row["documents_submitted"])
    docs = conn.execute(
        f"SELECT * FROM documents WHERE doc_id IN ({','.join('?'*len(doc_ids))})",
        doc_ids
    ).fetchall() if doc_ids else []

    all_verified = len(docs) > 0 and all(d["verified"] for d in docs)
    requested_level = row["requested_level"]
    meets_doc_requirements = _check_doc_requirements(requested_level, docs)

    if all_verified and meets_doc_requirements:
        new_status = KYCStatus.APPROVED.value
        notes = "All documents verified and requirements met."
        conn.execute(
            "UPDATE identities SET verification_level=? WHERE identity_id=?",
            (requested_level, row["identity_id"])
        )
    else:
        new_status = KYCStatus.REJECTED.value
        notes = "Insufficient verified documents or requirements not met."

    conn.execute(
        "UPDATE kyc_requests SET status=?, notes=?, processed_at=? WHERE request_id=?",
        (new_status, notes, now, request_id)
    )
    conn.commit()
    conn.close()
    _log_action(row["identity_id"], "PROCESS_KYC", f"KYC {request_id}: {new_status}")

    req = KYCRequest(
        identity_id=row["identity_id"],
        requested_level=VerificationLevel(requested_level),
        documents_submitted=doc_ids,
        status=KYCStatus(new_status),
        notes=notes,
        processed_at=now,
        request_id=request_id,
        created_at=row["created_at"]
    )
    return req


def _check_doc_requirements(level: str, docs: list) -> bool:
    """Check if documents meet the level requirements."""
    doc_types = {d["doc_type"] for d in docs}
    if level == VerificationLevel.BASIC.value:
        return len(docs) >= 1
    elif level == VerificationLevel.STANDARD.value:
        return len(docs) >= 2
    elif level == VerificationLevel.ENHANCED.value:
        primary = {DocType.PASSPORT.value, DocType.NATIONAL_ID.value}
        return len(docs) >= 3 and bool(primary & doc_types)
    return True


def check_verification_level(identity_id: str) -> dict:
    """Check the current verification level and status of an identity."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM identities WHERE identity_id=?", (identity_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Identity {identity_id} not found")
    docs = conn.execute(
        "SELECT * FROM documents WHERE identity_id=?", (identity_id,)
    ).fetchall()
    kyc_requests = conn.execute(
        "SELECT * FROM kyc_requests WHERE identity_id=? ORDER BY created_at DESC",
        (identity_id,)
    ).fetchall()
    conn.close()

    verified_docs = [d for d in docs if d["verified"]]
    pending_kyc = [k for k in kyc_requests if k["status"] in (KYCStatus.PENDING.value, KYCStatus.PROCESSING.value)]

    return {
        "identity_id": identity_id,
        "holder_name": row["holder_name"],
        "holder_email": row["holder_email"],
        "verification_level": row["verification_level"],
        "status": row["status"],
        "issued_at": row["issued_at"],
        "expires_at": row["expires_at"],
        "total_documents": len(docs),
        "verified_documents": len(verified_docs),
        "pending_kyc_requests": len(pending_kyc),
        "last_kyc_status": kyc_requests[0]["status"] if kyc_requests else None,
    }


def revoke_identity(identity_id: str, reason: str) -> bool:
    """Revoke a digital identity."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM identities WHERE identity_id=?", (identity_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Identity {identity_id} not found")
    conn.execute(
        "UPDATE identities SET status=? WHERE identity_id=?",
        (IdentityStatus.REVOKED.value, identity_id)
    )
    conn.commit()
    conn.close()
    _log_action(identity_id, "REVOKE_IDENTITY", f"Reason: {reason}")
    return True


def get_audit_trail(identity_id: str) -> List[dict]:
    """Get the full audit trail for an identity."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE identity_id=? ORDER BY timestamp ASC",
        (identity_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_identities(status: Optional[str] = None, level: Optional[str] = None) -> List[dict]:
    """List all identities with optional filters."""
    conn = get_connection()
    query = "SELECT * FROM identities WHERE 1=1"
    params = []
    if status:
        query += " AND status=?"
        params.append(status)
    if level:
        query += " AND verification_level=?"
        params.append(level)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def identity_stats() -> dict:
    """Get aggregate statistics about all identities."""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
    by_level = {}
    for level in VerificationLevel:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM identities WHERE verification_level=?",
            (level.value,)
        ).fetchone()[0]
        by_level[level.value] = cnt
    by_status = {}
    for st in IdentityStatus:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM identities WHERE status=?",
            (st.value,)
        ).fetchone()[0]
        by_status[st.value] = cnt
    pending_kyc = conn.execute(
        "SELECT COUNT(*) FROM kyc_requests WHERE status IN ('pending','processing')"
    ).fetchone()[0]
    total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    verified_docs = conn.execute("SELECT COUNT(*) FROM documents WHERE verified=1").fetchone()[0]
    conn.close()
    return {
        "total_identities": total,
        "by_verification_level": by_level,
        "by_status": by_status,
        "pending_kyc_requests": pending_kyc,
        "total_documents": total_docs,
        "verified_documents": verified_docs,
        "verification_rate": round(verified_docs / total_docs * 100, 2) if total_docs else 0.0,
    }


def expire_old_identities() -> int:
    """Mark expired identities as expired."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "UPDATE identities SET status=? WHERE expires_at < ? AND status=?",
        (IdentityStatus.EXPIRED.value, now, IdentityStatus.ACTIVE.value)
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def search_identity(query: str) -> List[dict]:
    """Search identities by name or email."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM identities WHERE holder_name LIKE ? OR holder_email LIKE ?",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_documents(identity_id: str) -> List[dict]:
    """Get all documents for an identity."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents WHERE identity_id=?", (identity_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_kyc_history(identity_id: str) -> List[dict]:
    """Get KYC request history for an identity."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM kyc_requests WHERE identity_id=? ORDER BY created_at DESC",
        (identity_id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["documents_submitted"] = json.loads(d["documents_submitted"])
        result.append(d)
    return result


def suspend_identity(identity_id: str, reason: str) -> bool:
    """Temporarily suspend an identity."""
    conn = get_connection()
    row = conn.execute("SELECT status FROM identities WHERE identity_id=?", (identity_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Identity {identity_id} not found")
    conn.execute(
        "UPDATE identities SET status=? WHERE identity_id=?",
        (IdentityStatus.SUSPENDED.value, identity_id)
    )
    conn.commit()
    conn.close()
    _log_action(identity_id, "SUSPEND_IDENTITY", f"Reason: {reason}")
    return True


def reactivate_identity(identity_id: str) -> bool:
    """Reactivate a suspended identity."""
    conn = get_connection()
    row = conn.execute("SELECT status FROM identities WHERE identity_id=?", (identity_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Identity {identity_id} not found")
    if row["status"] != IdentityStatus.SUSPENDED.value:
        conn.close()
        raise ValueError(f"Identity {identity_id} is not suspended")
    conn.execute(
        "UPDATE identities SET status=? WHERE identity_id=?",
        (IdentityStatus.ACTIVE.value, identity_id)
    )
    conn.commit()
    conn.close()
    _log_action(identity_id, "REACTIVATE_IDENTITY", "Identity reactivated")
    return True


def generate_identity_report(identity_id: str) -> str:
    """Generate a human-readable identity report."""
    info = check_verification_level(identity_id)
    docs = get_documents(identity_id)
    kyc = get_kyc_history(identity_id)
    audit = get_audit_trail(identity_id)

    lines = [
        "=" * 60,
        "DIGITAL IDENTITY REPORT",
        "=" * 60,
        f"Identity ID   : {info['identity_id']}",
        f"Holder Name   : {info['holder_name']}",
        f"Holder Email  : {info['holder_email']}",
        f"Status        : {info['status'].upper()}",
        f"Level         : {info['verification_level'].upper()}",
        f"Issued        : {info['issued_at'][:10]}",
        f"Expires       : {info['expires_at'][:10]}",
        "",
        f"Documents ({info['total_documents']} total, {info['verified_documents']} verified):",
    ]
    for d in docs:
        v = "✓" if d["verified"] else "✗"
        lines.append(f"  [{v}] {d['doc_type']} — {d['issuing_country']} — Exp: {d['expiry']}")

    lines.append("")
    lines.append(f"KYC Requests ({len(kyc)}):")
    for k in kyc:
        lines.append(f"  [{k['status'].upper()}] {k['requested_level']} — {k['created_at'][:10]}")
        if k["notes"]:
            lines.append(f"       Notes: {k['notes']}")

    lines.append("")
    lines.append(f"Audit Trail ({len(audit)} entries):")
    for a in audit[-5:]:
        lines.append(f"  {a['timestamp'][:19]} — {a['action']}")

    lines.append("=" * 60)
    return "\n".join(lines)


def cli():
    """Simple CLI interface."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python digital_identity.py <command> [args]")
        print("Commands: create, submit-doc, verify-doc, kyc, process-kyc, check, revoke, stats, report")
        return

    cmd = sys.argv[1]
    init_db()

    if cmd == "create" and len(sys.argv) >= 4:
        identity = create_identity(sys.argv[2], sys.argv[3])
        print(f"Created identity: {identity.identity_id}")

    elif cmd == "stats":
        stats = identity_stats()
        print(json.dumps(stats, indent=2))

    elif cmd == "list":
        identities = list_identities()
        for i in identities:
            print(f"{i['identity_id'][:8]}... {i['holder_name']} <{i['holder_email']}> [{i['verification_level']}]")

    elif cmd == "check" and len(sys.argv) >= 3:
        info = check_verification_level(sys.argv[2])
        print(json.dumps(info, indent=2))

    elif cmd == "report" and len(sys.argv) >= 3:
        print(generate_identity_report(sys.argv[2]))

    elif cmd == "expire":
        count = expire_old_identities()
        print(f"Expired {count} identities")

    elif cmd == "search" and len(sys.argv) >= 3:
        results = search_identity(sys.argv[2])
        for r in results:
            print(f"{r['identity_id'][:8]}... {r['holder_name']} [{r['verification_level']}]")

    else:
        print(f"Unknown command or missing arguments: {cmd}")


if __name__ == "__main__":
    cli()
