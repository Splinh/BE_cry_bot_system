"""
SQLite Database - Luu tru du lieu trading, signals, gems, wallets.
Thay the file JSON de scale tot hon.
"""
import sqlite3
import json
import os
import threading
from datetime import datetime
from loguru import logger


class Database:
    DB_PATH = "data/crypto_bot.db"
    _local = threading.local()

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
        self._init_tables()

    def _get_conn(self):
        """Thread-safe connection (SQLite ko cho share connection giua threads)."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_tables(self):
        conn = self._get_conn()
        conn.executescript("""
        -- Positions (Open + Closed)
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            coin TEXT NOT NULL,
            name TEXT DEFAULT '',
            direction TEXT DEFAULT 'LONG',
            type TEXT DEFAULT 'FUTURES',
            chain TEXT DEFAULT '',
            entry_price REAL NOT NULL,
            close_price REAL,
            current_price REAL,
            usdt_size REAL NOT NULL,
            leverage INTEGER DEFAULT 1,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            status TEXT DEFAULT 'OPEN',
            pnl REAL DEFAULT 0,
            closed_pct REAL DEFAULT 0,
            close_reason TEXT,
            wallet_id INTEGER,
            wallet_label TEXT,
            open_time TEXT,
            close_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Balance History (Nap/Rut)
        CREATE TABLE IF NOT EXISTS balance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_after REAL NOT NULL,
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Trading Account
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY DEFAULT 1,
            balance REAL DEFAULT 10000,
            auto_trade INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Signals Cache
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT NOT NULL,
            timeframe TEXT,
            direction TEXT,
            signal_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Gem Watchlist
        CREATE TABLE IF NOT EXISTS gem_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT,
            chain TEXT,
            address TEXT,
            price_at_add REAL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Users (Auth)
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            status TEXT DEFAULT 'pending',
            permissions TEXT DEFAULT '[]',
            approved_by INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- GameFi Tracker
        CREATE TABLE IF NOT EXISTS gamefi_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            chain TEXT DEFAULT 'SOL',
            token_price REAL DEFAULT 0,
            nft_floor_price REAL DEFAULT 0,
            daily_roi_estimate REAL DEFAULT 0,
            onchain_users_24h INTEGER DEFAULT 0,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Price Alerts
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            coin TEXT NOT NULL,
            target_price REAL NOT NULL,
            direction TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Init account if empty
        INSERT OR IGNORE INTO account (id, balance) VALUES (1, 10000);
        """)
        conn.commit()
        self._migrate_users_table()
        self._seed_default_admin()
        logger.info(f"SQLite DB ready: {self.DB_PATH}")

    # ==================
    # Account
    # ==================
    def get_balance(self) -> float:
        conn = self._get_conn()
        row = conn.execute("SELECT balance FROM account WHERE id=1").fetchone()
        return row["balance"] if row else 10000

    def update_balance(self, balance: float, auto_trade: bool = None):
        conn = self._get_conn()
        if auto_trade is not None:
            conn.execute("UPDATE account SET balance=?, auto_trade=?, updated_at=? WHERE id=1",
                         (balance, int(auto_trade), datetime.now().isoformat()))
        else:
            conn.execute("UPDATE account SET balance=?, updated_at=? WHERE id=1",
                         (balance, datetime.now().isoformat()))
        conn.commit()

    # ==================
    # Positions
    # ==================
    def save_position(self, key: str, pos: dict):
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO positions 
            (key, coin, name, direction, type, chain, entry_price, close_price, current_price,
             usdt_size, leverage, sl, tp1, tp2, tp3, status, pnl, closed_pct, 
             close_reason, wallet_id, wallet_label, open_time, close_time)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            key,
            pos.get("coin", ""),
            pos.get("name", ""),
            pos.get("direction", "LONG"),
            pos.get("type", "FUTURES"),
            pos.get("chain", ""),
            pos.get("entry_price", 0),
            pos.get("close_price"),
            pos.get("current_price"),
            pos.get("usdt_size", 0),
            pos.get("leverage", 1),
            pos.get("sl"),
            pos.get("tp1"),
            pos.get("tp2"),
            pos.get("tp3"),
            pos.get("status", "OPEN"),
            pos.get("pnl", 0),
            pos.get("closed_pct", 0),
            pos.get("close_reason"),
            pos.get("wallet_id"),
            pos.get("wallet_label"),
            pos.get("open_time"),
            pos.get("close_time"),
        ))
        conn.commit()

    def get_open_positions(self) -> list:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM positions WHERE status='OPEN' ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_closed_positions(self, limit=100) -> list:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM positions WHERE status!='OPEN' ORDER BY close_time DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close_position(self, key: str, close_price: float, pnl: float, reason: str):
        conn = self._get_conn()
        conn.execute("""
            UPDATE positions SET status='CLOSED', close_price=?, pnl=?, close_reason=?, 
            close_time=? WHERE key=?
        """, (close_price, pnl, reason, datetime.now().isoformat(), key))
        conn.commit()

    def delete_position(self, key: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM positions WHERE key=?", (key,))
        conn.commit()

    # ==================
    # Balance History
    # ==================
    def add_balance_record(self, type: str, amount: float, balance_after: float, note: str = ""):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO balance_history (type, amount, balance_after, note) VALUES (?,?,?,?)",
            (type, amount, balance_after, note)
        )
        conn.commit()

    def get_balance_history(self, limit=50) -> list:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM balance_history ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ==================
    # Signals
    # ==================
    def save_signal(self, coin: str, timeframe: str, direction: str, data: dict):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO signals (coin, timeframe, direction, signal_data) VALUES (?,?,?,?)",
            (coin, timeframe, direction, json.dumps(data))
        )
        conn.commit()

    def get_recent_signals(self, limit=20) -> list:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["signal_data"] = json.loads(d["signal_data"]) if d.get("signal_data") else {}
            result.append(d)
        return result

    # ==================
    # Gem Watchlist
    # ==================
    def add_to_watchlist(self, symbol: str, name: str, chain: str, address: str = "", 
                         price: float = 0, note: str = ""):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO gem_watchlist (symbol, name, chain, address, price_at_add, note) VALUES (?,?,?,?,?,?)",
            (symbol, name, chain, address, price, note)
        )
        conn.commit()

    def get_watchlist(self) -> list:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM gem_watchlist ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def remove_from_watchlist(self, id: int):
        conn = self._get_conn()
        conn.execute("DELETE FROM gem_watchlist WHERE id=?", (id,))
        conn.commit()

    # ==================
    # GameFi Projects
    # ==================
    def add_gamefi_project(self, name: str, symbol: str, chain: str = "SOL", 
                           token_price: float = 0, nft_floor_price: float = 0, 
                           daily_roi_estimate: float = 0, onchain_users_24h: int = 0, note: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO gamefi_projects 
               (name, symbol, chain, token_price, nft_floor_price, daily_roi_estimate, onchain_users_24h, note) 
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, symbol, chain, token_price, nft_floor_price, daily_roi_estimate, onchain_users_24h, note)
        )
        conn.commit()

    def get_gamefi_projects(self) -> list:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM gamefi_projects ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def update_gamefi_project(self, id: int, data: dict):
        conn = self._get_conn()
        fields = []
        values = []
        for k, v in data.items():
            if k in ["name", "symbol", "chain", "token_price", "nft_floor_price", "daily_roi_estimate", "onchain_users_24h", "note"]:
                fields.append(f"{k}=?")
                values.append(v)
        if fields:
            values.append(id)
            query = f"UPDATE gamefi_projects SET {', '.join(fields)} WHERE id=?"
            conn.execute(query, tuple(values))
            conn.commit()

    def remove_gamefi_project(self, id: int):
        conn = self._get_conn()
        conn.execute("DELETE FROM gamefi_projects WHERE id=?", (id,))
        conn.commit()

    # ==================
    # Migration from JSON
    # ==================
    def migrate_from_json(self, json_path: str = "data/paper_trading.json"):
        """Import du lieu tu file JSON cu sang SQLite."""
        if not os.path.exists(json_path):
            logger.info("No JSON data to migrate")
            return

        try:
            with open(json_path) as f:
                data = json.load(f)

            # Migrate balance
            balance = data.get("balance", 10000)
            self.update_balance(balance, data.get("auto_trade", False))

            # Migrate positions
            for key, pos in data.get("positions", {}).items():
                pos_copy = dict(pos)
                pos_copy.setdefault("status", "OPEN")
                self.save_position(key, pos_copy)

            # Migrate history
            for h in data.get("history", []):
                h_copy = dict(h)
                h_copy["status"] = "CLOSED"
                key = h_copy.pop("signal_key", f"HIST_{len(self.get_closed_positions())}")
                self.save_position(key, h_copy)

            # Migrate balance_history
            for bh in data.get("balance_history", []):
                self.add_balance_record(
                    bh.get("type", "DEPOSIT"),
                    bh.get("amount", 0),
                    bh.get("balance_after", 0),
                    bh.get("note", "")
                )

            # Backup old file
            backup = json_path + ".bak"
            os.rename(json_path, backup)
            logger.success(f"Migrated JSON -> SQLite! Backup: {backup}")
            logger.info(f"  Positions: {len(data.get('positions', {}))}")
            logger.info(f"  History: {len(data.get('history', []))}")
            logger.info(f"  Balance: ${balance:.2f}")

        except Exception as e:
            logger.error(f"Migration error: {e}")

    # ==================
    # Stats
    # ==================
    def get_stats(self) -> dict:
        conn = self._get_conn()
        open_count = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status='OPEN'").fetchone()["c"]
        closed_count = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status!='OPEN'").fetchone()["c"]
        total_pnl = conn.execute("SELECT COALESCE(SUM(pnl),0) as s FROM positions WHERE status!='OPEN'").fetchone()["s"]
        wins = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status!='OPEN' AND pnl > 0").fetchone()["c"]
        return {
            "open_positions": open_count,
            "closed_trades": closed_count,
            "total_pnl": round(total_pnl, 2),
            "win_count": wins,
            "win_rate": round(wins / closed_count * 100, 1) if closed_count > 0 else 0,
        }

    # ==================
    # Users (Auth)
    # ==================
    def _migrate_users_table(self):
        """Add new columns to users table if they don't exist (migration)."""
        conn = self._get_conn()
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        migrations = {
            "status": "ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'approved'",
            "permissions": "ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT '[]'",
            "approved_by": "ALTER TABLE users ADD COLUMN approved_by INTEGER",
        }
        for col, sql in migrations.items():
            if col not in columns:
                try:
                    conn.execute(sql)
                    conn.commit()
                    logger.info(f"Migrated users table: added '{col}'")
                except Exception as e:
                    logger.warning(f"Migration '{col}' skipped: {e}")
        
        # Grant all permissions to existing admin users with empty permissions
        all_perms = json.dumps([
            "overview", "trading", "analysis", "social",
            "wallets", "gems", "gamefi", "security", "users"
        ])
        conn.execute(
            "UPDATE users SET permissions=? WHERE role='admin' AND (permissions IS NULL OR permissions='[]')",
            (all_perms,)
        )
        conn.commit()

    def _seed_default_admin(self):
        """Create default admin if no users exist."""
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        if count == 0:
            import hashlib, secrets
            salt = secrets.token_hex(16)
            hashed = hashlib.sha256((salt + "admin123").encode()).hexdigest()
            password_hash = f"{salt}${hashed}"
            all_permissions = json.dumps([
                "overview", "trading", "analysis", "social",
                "wallets", "gems", "gamefi", "security", "users"
            ])
            conn.execute(
                "INSERT INTO users (username, email, password_hash, role, status, permissions, is_active) VALUES (?,?,?,?,?,?,?)",
                ("admin", "admin@system.local", password_hash, "admin", "approved", all_permissions, 1)
            )
            conn.commit()
            logger.success("[SEED] Default admin created (admin / admin123)")

    def create_user(self, username: str, email: str, password_hash: str, 
                    role: str = "user", status: str = "pending") -> dict:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO users (username, email, password_hash, role, status, permissions) VALUES (?,?,?,?,?,?)",
                (username, email, password_hash, role, status, "[]")
            )
            conn.commit()
            return self.get_user_by_username(username)
        except sqlite3.IntegrityError:
            return None

    def get_user_by_username(self, username: str) -> dict:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_all_users(self, status_filter: str = None) -> list:
        conn = self._get_conn()
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM users WHERE status=? ORDER BY created_at DESC",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def update_user_status(self, user_id: int, status: str, approved_by: int = None):
        conn = self._get_conn()
        conn.execute(
            "UPDATE users SET status=?, approved_by=? WHERE id=?",
            (status, approved_by, user_id)
        )
        conn.commit()

    def update_user_permissions(self, user_id: int, permissions: list):
        conn = self._get_conn()
        conn.execute(
            "UPDATE users SET permissions=? WHERE id=?",
            (json.dumps(permissions), user_id)
        )
        conn.commit()

    def update_user_role(self, user_id: int, role: str):
        conn = self._get_conn()
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        conn.commit()

    def toggle_user_active(self, user_id: int) -> bool:
        conn = self._get_conn()
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        new_active = 0 if user["is_active"] else 1
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (new_active, user_id))
        conn.commit()
        return True

    def delete_user(self, user_id: int):
        conn = self._get_conn()
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()

    # ==================
    # Price Alerts
    # ==================
    def add_price_alert(self, chat_id: int, coin: str, target_price: float, direction: str) -> int:
        """Them price alert moi. direction: 'above' hoac 'below'."""
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO price_alerts (chat_id, coin, target_price, direction) VALUES (?,?,?,?)",
            (chat_id, coin.upper(), target_price, direction)
        )
        conn.commit()
        return cursor.lastrowid

    def get_active_alerts(self, chat_id: int = None) -> list:
        """Lay tat ca alerts dang active (tuy chon loc theo chat_id)."""
        conn = self._get_conn()
        if chat_id:
            rows = conn.execute(
                "SELECT * FROM price_alerts WHERE is_active=1 AND chat_id=? ORDER BY created_at DESC",
                (chat_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM price_alerts WHERE is_active=1 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def deactivate_alert(self, alert_id: int):
        conn = self._get_conn()
        conn.execute("UPDATE price_alerts SET is_active=0 WHERE id=?", (alert_id,))
        conn.commit()

    def delete_alert(self, alert_id: int, chat_id: int = None):
        conn = self._get_conn()
        if chat_id:
            conn.execute("DELETE FROM price_alerts WHERE id=? AND chat_id=?", (alert_id, chat_id))
        else:
            conn.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))
        conn.commit()


# Singleton
db = Database()
