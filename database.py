import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'financa.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT UNIQUE,
                description TEXT,
                amount      REAL,
                type        TEXT,
                category    TEXT,
                date_created DATETIME,
                synced_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS balances (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                available  REAL,
                total      REAL,
                synced_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    print('[DB] Banco iniciado em', DB_PATH)


# ── CONFIG ──────────────────────────────────────────────

def get_config(key):
    with get_conn() as conn:
        row = conn.execute('SELECT value FROM config WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else None


def set_config(key, value):
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
            (key, value, datetime.utcnow().isoformat())
        )


# ── TRANSACTIONS ─────────────────────────────────────────

def save_transactions(movements: list):
    saved = 0
    with get_conn() as conn:
        for m in movements:
            try:
                conn.execute(
                    '''INSERT OR IGNORE INTO transactions
                       (external_id, description, amount, type, date_created)
                       VALUES (?, ?, ?, ?, ?)''',
                    (
                        str(m.get('id', '')),
                        m.get('description') or m.get('type') or 'Transação',
                        float(m.get('amount', 0)),
                        m.get('type', ''),
                        m.get('date_created', datetime.utcnow().isoformat()),
                    )
                )
                saved += conn.execute('SELECT changes()').fetchone()[0]
            except Exception as e:
                print(f'[DB] Erro ao salvar transação {m.get("id")}: {e}')
    return saved


def get_transactions(limit=50, month=None):
    with get_conn() as conn:
        if month:
            rows = conn.execute(
                '''SELECT * FROM transactions
                   WHERE strftime('%Y-%m', date_created) = ?
                   ORDER BY date_created DESC LIMIT ?''',
                (month, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM transactions ORDER BY date_created DESC LIMIT ?',
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_monthly_summary(month=None):
    if not month:
        month = datetime.utcnow().strftime('%Y-%m')
    with get_conn() as conn:
        row = conn.execute(
            '''SELECT
                COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS entradas,
                COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS saidas,
                COUNT(*) AS total_tx
               FROM transactions
               WHERE strftime('%Y-%m', date_created) = ?''',
            (month,)
        ).fetchone()
        return dict(row) if row else {'entradas': 0, 'saidas': 0, 'total_tx': 0}


def get_daily_summary(date=None):
    if not date:
        from datetime import timedelta
        date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    with get_conn() as conn:
        rows = conn.execute(
            '''SELECT description, amount, type, date_created
               FROM transactions
               WHERE date(date_created) = ?
               ORDER BY date_created DESC''',
            (date,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── BALANCES ─────────────────────────────────────────────

def save_balance(available: float, total: float = 0):
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO balances (available, total) VALUES (?, ?)',
            (available, total)
        )


def get_latest_balance():
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM balances ORDER BY synced_at DESC LIMIT 1'
        ).fetchone()
        return dict(row) if row else {'available': 0, 'total': 0}
