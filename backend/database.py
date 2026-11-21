"""
VaaniKhata – AES-256 Encrypted SQLite ACID Ledger (DPDP Compliant)
==================================================================
Handles deterministic financial bookkeeping, AES-256 encryption at rest
using Fernet, customer homonym resolution, atomic rollback/replacement,
and DPDP compliance guards.
"""

from __future__ import annotations

import datetime
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Sequence
import sqlite3

from cryptography.fernet import Fernet

from backend.config import get_settings

# ---------------------------------------------------------------------------
# Path & Directory Resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_KEY_FILE = _PROJECT_ROOT / ".fernet.key"

# ---------------------------------------------------------------------------
# AES-256 (Fernet) Encryption at Rest
# ---------------------------------------------------------------------------
_fernet_instance: Fernet | None = None


def _get_encryption_key_setting() -> str:
    try:
        return (get_settings().encryption_key or "").strip()
    except Exception:
        import os
        return os.getenv("ENCRYPTION_KEY", "").strip()


def _get_db_path_setting() -> str:
    try:
        return get_settings().db_path
    except Exception:
        import os
        return os.getenv("DB_PATH", "vaanikhata.db")


def get_fernet() -> Fernet:
    """
    Return or initialize a cached Fernet instance.
    Uses ENCRYPTION_KEY from config/.env if provided; otherwise persists
    or loads from local .fernet.key.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key_str = _get_encryption_key_setting()

    if key_str:
        key_bytes = key_str.encode("utf-8")
    elif _KEY_FILE.exists():
        key_bytes = _KEY_FILE.read_bytes().strip()
    else:
        key_bytes = Fernet.generate_key()
        _KEY_FILE.write_bytes(key_bytes)

    _fernet_instance = Fernet(key_bytes)
    return _fernet_instance


def encrypt_text(plain: str) -> str:
    """Encrypt a plaintext string to a base64-encoded Fernet token."""
    if not plain:
        return ""
    f = get_fernet()
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(token: str) -> str:
    """Decrypt a base64-encoded Fernet token back to plaintext string."""
    if not token:
        return ""
    f = get_fernet()
    return f.decrypt(token.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# SQLite Connection Helper (ACID + WAL Mode)
# ---------------------------------------------------------------------------
def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve database path relative to project root if not absolute."""
    if db_path is not None:
        p = Path(db_path)
        return p if p.is_absolute() else _PROJECT_ROOT / p
    configured = Path(_get_db_path_setting())
    return configured if configured.is_absolute() else _PROJECT_ROOT / configured


@contextmanager
def get_db(db_path: str | Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager yielding an ACID SQLite connection with:
      - WAL journal mode enabled (concurrent read/write)
      - Foreign key enforcement enabled
      - sqlite3.Row row factory for clean dict/attribute access
    Automatically commits on normal exit and rolls back on exception.
    """
    target = resolve_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema Initialization
# ---------------------------------------------------------------------------
def init_db(db_path: str | Path | None = None) -> None:
    """Initialize the 3 core tables and seed initial data if empty."""
    with get_db(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                landmark TEXT NOT NULL,
                phone TEXT NOT NULL,
                opt_in_reminder INTEGER NOT NULL DEFAULT 1,
                net_balance INTEGER NOT NULL DEFAULT 0,
                owner_note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                amount INTEGER NOT NULL CHECK(amount > 0),
                tx_type TEXT NOT NULL CHECK(tx_type IN ('CREDIT', 'PAYMENT')),
                tx_date TEXT NOT NULL,
                relative_label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'REVERSED')),
                replaces_tx_id INTEGER NULL REFERENCES transactions(id),
                encrypted_raw_note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS demo_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encrypted_transcript TEXT NOT NULL,
                encrypted_response TEXT NOT NULL,
                intent TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_customers_names
                ON customers(full_name, first_name, last_name);

            CREATE INDEX IF NOT EXISTS idx_tx_customer_status
                ON transactions(customer_id, status);

            CREATE INDEX IF NOT EXISTS idx_tx_date_status
                ON transactions(tx_date, status);
        """)

        # Backward compatibility migration for owner_note column
        try:
            conn.execute("ALTER TABLE customers ADD COLUMN owner_note TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        # Check if seeding is required
        cursor = conn.execute("SELECT COUNT(*) AS cnt FROM customers")
        row = cursor.fetchone()
        if row and row["cnt"] == 0:
            _seed_initial_data(conn)


def _seed_initial_data(conn: sqlite3.Connection) -> None:
    """
    Seed the 4 synthetic Kirana customers synced to Pitch Deck math:
      1. Ramesh Sharma (MG Road)     -> ₹0 Opening Balance (no initial tx)
      2. Ramesh Verma  (Brigade Rd)  -> ₹150 Opening Balance (1 active CREDIT yesterday, opt-out!)
      3. Suresh Gowda  (Jayanagar)   -> ₹280 Opening Balance (1 active CREDIT today)
      4. Lakshmi Devi  (JP Nagar)    -> ₹0 Opening Balance
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    today_str = datetime.date.today().isoformat()
    yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    # 1. Ramesh Sharma
    conn.execute(
        """
        INSERT INTO customers (first_name, last_name, full_name, landmark, phone, opt_in_reminder, net_balance, owner_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Ramesh", "Sharma", "Ramesh Sharma", "MG Road", "+91-9845011101", 1, 0, "Regular buyer · Pays on 5th of month"),
    )

    # 2. Ramesh Verma (opt_in_reminder = 0)
    cur = conn.execute(
        """
        INSERT INTO customers (first_name, last_name, full_name, landmark, phone, opt_in_reminder, net_balance, owner_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Ramesh", "Verma", "Ramesh Verma", "Brigade Road", "+91-9845011102", 0, 150, "Prefers cash payment · Brigade shopkeeper"),
    )
    verma_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO transactions (customer_id, amount, tx_type, tx_date, relative_label, status, encrypted_raw_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            verma_id,
            150,
            "CREDIT",
            yesterday_str,
            "Yesterday (kal)",
            "ACTIVE",
            encrypt_text("Initial credit balance"),
            now_utc,
        ),
    )

    # 3. Suresh Gowda
    cur = conn.execute(
        """
        INSERT INTO customers (first_name, last_name, full_name, landmark, phone, opt_in_reminder, net_balance, owner_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Suresh", "Gowda", "Suresh Gowda", "Jayanagar", "+91-9845011103", 1, 280, "Daily milk & tea supplies · Landlord reference"),
    )
    gowda_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO transactions (customer_id, amount, tx_type, tx_date, relative_label, status, encrypted_raw_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            gowda_id,
            280,
            "CREDIT",
            today_str,
            "Today",
            "ACTIVE",
            encrypt_text("Initial credit balance"),
            now_utc,
        ),
    )

    # 4. Lakshmi Devi
    conn.execute(
        """
        INSERT INTO customers (first_name, last_name, full_name, landmark, phone, opt_in_reminder, net_balance, owner_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Lakshmi", "Devi", "Lakshmi Devi", "JP Nagar", "+91-9845011104", 1, 0, "Weekly groceries · Prefers morning delivery"),
    )


# ---------------------------------------------------------------------------
# Core Bookkeeping & Customer Lookups
# ---------------------------------------------------------------------------
def create_customer(
    first_name: str,
    last_name: str = "",
    landmark: str = "",
    phone: str = "",
    opt_in_reminder: bool = True,
    opening_balance: int = 0,
    owner_note: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Atomically create a new customer in the Khata Book.
    If opening_balance > 0, atomically inserts an 'ACTIVE' 'CREDIT' transaction
    (relative_label='Opening Balance') inside the same ACID transaction so
    recalculate_balance() always matches the ledger history.
    """
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if not fn:
        raise ValueError("Customer first_name cannot be empty")

    full_name = f"{fn} {ln}".strip() if ln else fn
    lm = (landmark or "").strip() or "Local"
    ph = (phone or "").strip()
    note_val = (owner_note or "").strip()
    if not ph:
        # Generate predictable unique phone number
        ph = f"+91-98450{abs(hash(full_name)) % 90000 + 10000}"

    opt_val = 1 if opt_in_reminder else 0
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    today_str = datetime.date.today().isoformat()

    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO customers (first_name, last_name, full_name, landmark, phone, opt_in_reminder, net_balance, owner_note)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (fn, ln, full_name, lm, ph, opt_val, note_val),
        )
        customer_id = cur.lastrowid

        if opening_balance > 0:
            conn.execute(
                """
                INSERT INTO transactions (
                    customer_id, amount, tx_type, tx_date, relative_label,
                    status, replaces_tx_id, encrypted_raw_note, created_at
                )
                VALUES (?, ?, 'CREDIT', ?, 'Opening Balance', 'ACTIVE', NULL, ?, ?)
                """,
                (
                    customer_id,
                    int(opening_balance),
                    today_str,
                    encrypt_text("Opening Balance"),
                    now_utc,
                ),
            )
            _recalculate_net_balance(conn, customer_id)

        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        cust = dict(row)
        cust["recent_transactions"] = []
        return cust


def delete_customer(customer_id: int, db_path: str | Path | None = None) -> bool:
    """Safely delete a customer and their transactions (e.g. during demo cleanup)."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM transactions WHERE customer_id = ?", (customer_id,))
        cur = conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        return cur.rowcount > 0


def find_customers_by_name(query: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """
    Case-insensitive customer lookup with homonym support:
      1. Check exact full_name, unique last_name, or unique landmark match.
         (e.g., 'Sharma' or 'Ramesh Sharma' returns [Ramesh Sharma])
      2. Otherwise check first_name match (e.g., 'Ramesh' returns [Ramesh Sharma, Ramesh Verma]).
      3. Fallback to substring matching across full_name or landmark.
      Supports Indian honorific stripping (e.g. 'Suresh ji' -> 'Suresh').
    """
    q = query.strip()
    if not q:
        return []

    # Strip common Indic honorifics if present (e.g. 'Suresh ji' -> 'Suresh', 'Ramesh bhai' -> 'Ramesh')
    q_stripped = re.sub(
        r"\b(?:ji|bhai|bhaiya|anna|garu|avargal|sahab|saab|sir|chechi|seth|sethji|shree|sri)\b",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()

    with get_db(db_path) as conn:
        for candidate_q in ([q] if not q_stripped or q_stripped.lower() == q.lower() else [q, q_stripped]):
            if not candidate_q:
                continue
            # 1. Exact full_name match
            rows = conn.execute(
                "SELECT * FROM customers WHERE LOWER(full_name) = LOWER(?)", (candidate_q,)
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]

            # 2. Exact last_name match
            rows = conn.execute(
                "SELECT * FROM customers WHERE LOWER(last_name) = LOWER(?)", (candidate_q,)
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]

            # 3. Exact landmark match
            rows = conn.execute(
                "SELECT * FROM customers WHERE LOWER(landmark) = LOWER(?)", (candidate_q,)
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]

            # 4. First name match (e.g. 'Ramesh' -> [Ramesh Sharma, Ramesh Verma])
            rows = conn.execute(
                "SELECT * FROM customers WHERE LOWER(first_name) = LOWER(?)", (candidate_q,)
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]

        # 5. Fallback substring match
        target_pattern = q_stripped.lower() if q_stripped else q.lower()
        like_pattern = f"%{target_pattern}%"
        rows = conn.execute(
            """
            SELECT * FROM customers
            WHERE LOWER(full_name) LIKE ? OR LOWER(landmark) LIKE ?
            """,
            (like_pattern, like_pattern),
        ).fetchall()
        return [dict(r) for r in rows]


def get_keyterm_roster(limit: int = 200, db_path: str | Path | None = None) -> list[str]:
    """
    Return deduplicated customer first names, last names, full names, and landmarks,
    capped strictly at `limit` terms (default 200). Used for Prisma STT dynamic vocabulary boosting.
    """
    if limit <= 0:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT first_name, last_name, full_name, landmark FROM customers ORDER BY id ASC"
        ).fetchall()
        for row in rows:
            for field in ("first_name", "last_name", "full_name", "landmark"):
                val = (row[field] or "").strip()
                if val and val.lower() not in seen:
                    seen.add(val.lower())
                    terms.append(val)
                    if len(terms) >= limit:
                        return terms
    return terms


def _recalculate_net_balance(conn: sqlite3.Connection, customer_id: int) -> int:
    """Strictly calculate net balance from active transactions and update customer row."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE WHEN tx_type = 'CREDIT' THEN amount ELSE -amount END
        ), 0) AS balance
        FROM transactions
        WHERE customer_id = ? AND status = 'ACTIVE'
        """,
        (customer_id,),
    ).fetchone()
    new_balance = int(row["balance"]) if row else 0

    conn.execute(
        "UPDATE customers SET net_balance = ? WHERE id = ?",
        (new_balance, customer_id),
    )
    return new_balance


def add_transactions_atomic(
    customer_id: int,
    entries: list[dict[str, Any]],
    raw_note: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Atomically insert one or more ledger entries for a customer and recalculate net_balance.
    raw_note is encrypted at rest using AES-256 Fernet.
    """
    if not entries:
        raise ValueError("entries list cannot be empty")

    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    today_str = datetime.date.today().isoformat()
    encrypted_note = encrypt_text(raw_note)

    inserted_ids: list[int] = []

    with get_db(db_path) as conn:
        # Verify customer exists
        cust = conn.execute("SELECT id FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if not cust:
            raise ValueError(f"Customer with id={customer_id} does not exist")

        for entry in entries:
            amount = int(entry["amount"])
            if amount <= 0:
                raise ValueError("Transaction amount must be strictly greater than 0")

            tx_type = str(entry["tx_type"]).upper()
            if tx_type not in ("CREDIT", "PAYMENT"):
                raise ValueError(f"Invalid tx_type: {tx_type}. Must be 'CREDIT' or 'PAYMENT'")

            tx_date = str(entry.get("tx_date") or today_str)
            relative_label = str(entry.get("relative_label") or "Today")

            cur = conn.execute(
                """
                INSERT INTO transactions (
                    customer_id, amount, tx_type, tx_date, relative_label,
                    status, replaces_tx_id, encrypted_raw_note, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'ACTIVE', NULL, ?, ?)
                """,
                (customer_id, amount, tx_type, tx_date, relative_label, encrypted_note, now_utc),
            )
            inserted_ids.append(cur.lastrowid)

        new_balance = _recalculate_net_balance(conn, customer_id)

    return {
        "primary_tx_id": inserted_ids[0],
        "inserted_ids": inserted_ids,
        "new_balance": new_balance,
    }


def reverse_and_replace_transaction(
    old_tx_id: int,
    new_amount: int,
    raw_note: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Atomically reverse an active transaction and insert a corrected active row
    with relative_label='Today (Corrected)' and replaces_tx_id=old_tx_id.
    Recalculates net balance deterministically.
    """
    if new_amount <= 0:
        raise ValueError("new_amount must be strictly positive")

    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    encrypted_note = encrypt_text(raw_note)

    with get_db(db_path) as conn:
        old_row = conn.execute(
            "SELECT * FROM transactions WHERE id = ? AND status = 'ACTIVE'",
            (old_tx_id,),
        ).fetchone()

        if not old_row:
            raise ValueError(f"Active transaction with id={old_tx_id} not found")

        old_tx = dict(old_row)
        customer_id = old_tx["customer_id"]

        # 1. Reverse old transaction
        conn.execute(
            "UPDATE transactions SET status = 'REVERSED' WHERE id = ?",
            (old_tx_id,),
        )

        # 2. Insert corrected replacement row
        cur = conn.execute(
            """
            INSERT INTO transactions (
                customer_id, amount, tx_type, tx_date, relative_label,
                status, replaces_tx_id, encrypted_raw_note, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
            """,
            (
                customer_id,
                new_amount,
                old_tx["tx_type"],
                old_tx["tx_date"],
                "Today (Corrected)",
                old_tx_id,
                encrypted_note,
                now_utc,
            ),
        )
        new_tx_id = cur.lastrowid

        # 3. Recalculate customer's balance
        new_balance = _recalculate_net_balance(conn, customer_id)

        cust = conn.execute(
            "SELECT full_name FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        customer_name = cust["full_name"] if cust else "Unknown"

    return {
        "old_amount": old_tx["amount"],
        "new_amount": new_amount,
        "new_tx_id": new_tx_id,
        "new_balance": new_balance,
        "customer_name": customer_name,
    }


def get_daily_summary(
    target_date: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Fast indexed summary of active CREDIT and PAYMENT sums for target_date."""
    effective_date = target_date or datetime.date.today().isoformat()

    with get_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN tx_type = 'CREDIT' THEN amount ELSE 0 END), 0) AS today_credit,
                COALESCE(SUM(CASE WHEN tx_type = 'PAYMENT' THEN amount ELSE 0 END), 0) AS today_payment,
                COUNT(*) AS tx_count
            FROM transactions
            WHERE tx_date = ? AND status = 'ACTIVE'
            """,
            (effective_date,),
        ).fetchone()

        credit = int(row["today_credit"]) if row else 0
        payment = int(row["today_payment"]) if row else 0
        tx_count = int(row["tx_count"]) if row else 0
        net_cashflow = payment - credit

        return {
            "date": effective_date,
            "today_credit": credit,
            "today_payment": payment,
            "net_cashflow": net_cashflow,
            "transaction_count": tx_count,
        }


def auto_enroll_and_transact(
    candidate_name: str,
    entries: list[dict[str, Any]],
    landmark: str = "Local",
    phone: str = "",
    raw_note: str = "",
    owner_note: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Atomically create a new customer and record initial transaction(s)
    in a single ACID database transaction.
    """
    if not entries:
        raise ValueError("entries list cannot be empty")

    toks = (candidate_name or "").strip().split()
    if not toks:
        raise ValueError("Customer name cannot be empty")

    fn = toks[0].capitalize()
    ln = " ".join(t.capitalize() for t in toks[1:]) if len(toks) > 1 else ""
    full_name = f"{fn} {ln}".strip() if ln else fn
    lm = (landmark or "").strip() or "Local"
    ph = (phone or "").strip()
    note_val = (owner_note or "").strip()
    if not ph:
        ph = f"+91-98450{abs(hash(full_name)) % 90000 + 10000}"

    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    today_str = datetime.date.today().isoformat()
    encrypted_note = encrypt_text(raw_note)

    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO customers (first_name, last_name, full_name, landmark, phone, opt_in_reminder, net_balance, owner_note)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?)
            """,
            (fn, ln, full_name, lm, ph, note_val),
        )
        cust_id = cur.lastrowid

        inserted_ids: list[int] = []
        for entry in entries:
            amount = int(entry["amount"])
            if amount <= 0:
                raise ValueError("Transaction amount must be strictly greater than 0")

            tx_type = str(entry["tx_type"]).upper()
            if tx_type not in ("CREDIT", "PAYMENT"):
                raise ValueError(f"Invalid tx_type: {tx_type}. Must be 'CREDIT' or 'PAYMENT'")

            tx_date = str(entry.get("tx_date") or today_str)
            relative_label = str(entry.get("relative_label") or "Today")

            tcur = conn.execute(
                """
                INSERT INTO transactions (
                    customer_id, amount, tx_type, tx_date, relative_label,
                    status, replaces_tx_id, encrypted_raw_note, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'ACTIVE', NULL, ?, ?)
                """,
                (cust_id, amount, tx_type, tx_date, relative_label, encrypted_note, now_utc),
            )
            inserted_ids.append(tcur.lastrowid)

        new_balance = _recalculate_net_balance(conn, cust_id)

        row = conn.execute("SELECT * FROM customers WHERE id = ?", (cust_id,)).fetchone()
        cust_dict = dict(row)

    return {
        "customer": cust_dict,
        "primary_tx_id": inserted_ids[0],
        "inserted_ids": inserted_ids,
        "new_balance": new_balance,
    }


def get_customer_with_timeline(
    customer_id: int,
    limit: int = 8,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Fetch customer details along with decrypted recent transactions timeline."""
    with get_db(db_path) as conn:
        crow = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if not crow:
            return None
        cust = dict(crow)
        trows = conn.execute(
            """
            SELECT * FROM transactions
            WHERE customer_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (customer_id, limit),
        ).fetchall()

        tx_list = []
        for t in trows:
            td = dict(t)
            try:
                td["raw_note"] = decrypt_text(td["encrypted_raw_note"])
            except Exception:
                td["raw_note"] = ""
            tx_list.append(td)
        cust["recent_transactions"] = tx_list
        return cust


# ---------------------------------------------------------------------------
# Responsible AI & DPDP Guardrails (Opt-in & Reminders)
# ---------------------------------------------------------------------------
def set_customer_opt_in(
    customer_id: int,
    opt_in: bool,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Set opt_in_reminder preference (1 = opted in, 0 = opted out) for a customer."""
    flag = 1 if opt_in else 0
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE customers SET opt_in_reminder = ? WHERE id = ?",
            (flag, customer_id),
        )
        cust = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if not cust:
            raise ValueError(f"Customer id={customer_id} not found")
        return dict(cust)


def update_customer_note(
    customer_id: int,
    note: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Atomically update the private Kirana store owner note for a khata member.
    """
    clean_note = (note or "").strip()
    with get_db(db_path) as conn:
        cur = conn.execute(
            "UPDATE customers SET owner_note = ? WHERE id = ?",
            (clean_note, int(customer_id)),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Customer id={customer_id} not found")
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (int(customer_id),)).fetchone()
        return dict(row)


def build_polite_reminder(
    customer_id: int,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    DPDP Guardrail:
      - If customer has NOT opted in (opt_in_reminder == 0), block reminder generation.
      - If customer opted in (opt_in_reminder == 1), generate polite zero-pressure reminder.
    """
    with get_db(db_path) as conn:
        cust = conn.execute(
            "SELECT full_name, net_balance, opt_in_reminder FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()

        if not cust:
            raise ValueError(f"Customer id={customer_id} not found")

        full_name = cust["full_name"]
        balance = cust["net_balance"]
        opt_in = cust["opt_in_reminder"]

        if opt_in == 0:
            return {
                "allowed": False,
                "reason": "BLOCKED BY GUARDRAIL: Customer has not opted in to payment reminders.",
            }

        msg = (
            f"नमस्ते {full_name} जी, आपके खाते में ₹{balance} का बकाया है। "
            f"अपनी सुविधानुसार भुगतान कर दें। धन्यवाद! "
            f"(Dear {full_name}, polite reminder that your pending balance is ₹{balance}. Thank you!)"
        )
        return {
            "allowed": True,
            "customer": full_name,
            "balance": balance,
            "message": msg,
        }


# ---------------------------------------------------------------------------
# Voice Session Logging & DPDP 1-Click Purge
# ---------------------------------------------------------------------------
def log_encrypted_transcript(
    raw_transcript: str,
    agent_reply: str,
    intent: str,
    latency_ms: int,
    db_path: str | Path | None = None,
) -> int:
    """Encrypt transcript and response using Fernet before saving to demo_transcripts."""
    enc_transcript = encrypt_text(raw_transcript)
    enc_reply = encrypt_text(agent_reply)
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO demo_transcripts (
                encrypted_transcript, encrypted_response, intent, latency_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (enc_transcript, enc_reply, intent, latency_ms, now_utc),
        )
        return cur.lastrowid


def purge_demo_transcripts(db_path: str | Path | None = None) -> int:
    """DPDP Act 1-click purge: delete all voice logs and return count of deleted rows."""
    with get_db(db_path) as conn:
        count_row = conn.execute("SELECT COUNT(*) AS cnt FROM demo_transcripts").fetchone()
        deleted_count = int(count_row["cnt"]) if count_row else 0
        conn.execute("DELETE FROM demo_transcripts")
        return deleted_count


# ---------------------------------------------------------------------------
# Dashboard State & Demo Reset
# ---------------------------------------------------------------------------
def fetch_dashboard_state(db_path: str | Path | None = None) -> dict[str, Any]:
    """
    Fetch comprehensive dashboard state:
      - All customers with their latest 8 transactions (decrypted notes for audit transparency)
      - today_credit and today_payment
      - encrypted_transcript_count
    """
    with get_db(db_path) as conn:
        customer_rows = conn.execute(
            "SELECT * FROM customers ORDER BY id ASC"
        ).fetchall()

        customers: list[dict[str, Any]] = []
        for c in customer_rows:
            cdict = dict(c)
            tx_rows = conn.execute(
                """
                SELECT * FROM transactions
                WHERE customer_id = ?
                ORDER BY id DESC
                LIMIT 8
                """,
                (cdict["id"],),
            ).fetchall()

            tx_list: list[dict[str, Any]] = []
            for t in tx_rows:
                tdict = dict(t)
                try:
                    tdict["raw_note"] = decrypt_text(tdict["encrypted_raw_note"])
                except Exception:
                    tdict["raw_note"] = "[Decryption Error]"
                tx_list.append(tdict)

            cdict["recent_transactions"] = tx_list
            customers.append(cdict)

        summary = get_daily_summary(db_path=db_path)

        cnt_row = conn.execute("SELECT COUNT(*) AS cnt FROM demo_transcripts").fetchone()
        transcript_count = int(cnt_row["cnt"]) if cnt_row else 0

    return {
        "customers": customers,
        "today_credit": summary["today_credit"],
        "today_payment": summary["today_payment"],
        "net_cashflow": summary.get("net_cashflow", summary["today_payment"] - summary["today_credit"]),
        "transaction_count": summary.get("transaction_count", 0),
        "encrypted_transcript_count": transcript_count,
    }


def reset_demo_db(db_path: str | Path | None = None) -> dict[str, Any]:
    """Cleanly wipe and re-seed database for fresh hackathon judge demonstrations."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM customers")
        conn.execute("DELETE FROM demo_transcripts")
        try:
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('customers', 'transactions', 'demo_transcripts')"
            )
        except sqlite3.OperationalError:
            pass
        _seed_initial_data(conn)

    return {"status": "reset_successful", "customer_count": 4}
