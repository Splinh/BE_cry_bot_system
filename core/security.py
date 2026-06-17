"""
Security Module - Bao mat cho Crypto Bot.
- Whitelist Chat ID (chi user duoc phep dung bot)
- PIN xac nhan giao dich (buy/send/claim)
- Gioi han so tien moi giao dich
- Rate limiting (chong spam lenh)
- Honeypot detection (kiem tra token truoc khi mua)
- Audit log (ghi lai moi hanh dong)
"""
import os
import json
import time
import hashlib
from datetime import datetime
from typing import Optional
from pathlib import Path
from loguru import logger


DATA_DIR = Path("data/security")
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "security_config.json"
AUDIT_LOG = DATA_DIR / "audit_log.json"


class SecurityManager:
    """
    Quan ly bao mat toan bo bot:
    1. Whitelist - Chi cho phep cac Chat ID duoc dung
    2. PIN - Xac nhan truoc khi giao dich
    3. TX Limits - Gioi han so tien
    4. Rate Limit - Chong spam
    5. Honeypot Check - Kiem tra token scam
    6. Audit Log - Ghi lai lich su
    """

    DEFAULT_CONFIG = {
        "whitelist_enabled": True,
        "whitelist_ids": [],       # Danh sach Chat IDs duoc phep
        "admin_ids": [],           # Admin co quyen thay doi settings
        "pin_enabled": False,
        "pin_hash": "",            # SHA256 hash cua PIN
        "pin_required_for": ["buy", "send", "claim", "farm", "export_key"],
        "tx_limit_enabled": True,
        "tx_limit_per_tx": 0.1,    # Max 0.1 ETH moi giao dich
        "tx_limit_daily": 1.0,     # Max 1 ETH/ngay
        "rate_limit_enabled": True,
        "rate_limit_commands": 30,  # Max 30 lenh/phut
        "rate_limit_tx": 10,       # Max 10 giao dich/gio
        "auto_lock_minutes": 60,   # Khoa sau 60 phut khong hoat dong
        "honeypot_check": True,    # Kiem tra token truoc khi mua
    }

    def __init__(self):
        self.config = self._load_config()
        self._rate_tracker: dict[str, list[float]] = {}  # chat_id -> [timestamps]
        self._tx_tracker: dict[str, list[dict]] = {}     # chat_id -> [{amount, time}]
        self._pin_verified: dict[str, float] = {}        # chat_id -> last_verified_time
        self._last_activity: dict[str, float] = {}       # chat_id -> last_activity_time

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    stored = json.load(f)
                # Merge voi default (de them key moi)
                config = {**self.DEFAULT_CONFIG, **stored}
                return config
            except Exception:
                pass
        return self.DEFAULT_CONFIG.copy()

    def _save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    # ==================================================
    # WHITELIST
    # ==================================================

    def add_whitelist(self, chat_id: int):
        """Them Chat ID vao whitelist."""
        if chat_id not in self.config["whitelist_ids"]:
            self.config["whitelist_ids"].append(chat_id)
            self._save_config()
            logger.info(f"Da them whitelist: {chat_id}")

    def remove_whitelist(self, chat_id: int):
        if chat_id in self.config["whitelist_ids"]:
            self.config["whitelist_ids"].remove(chat_id)
            self._save_config()

    def add_admin(self, chat_id: int):
        """Them admin (co quyen thay doi settings)."""
        if chat_id not in self.config["admin_ids"]:
            self.config["admin_ids"].append(chat_id)
            if chat_id not in self.config["whitelist_ids"]:
                self.config["whitelist_ids"].append(chat_id)
            self._save_config()

    def is_whitelisted(self, chat_id: int) -> bool:
        if not self.config["whitelist_enabled"]:
            return True
        if not self.config["whitelist_ids"]:
            return True  # Chua setup whitelist -> cho tat ca
        return chat_id in self.config["whitelist_ids"]

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.config["admin_ids"]

    # ==================================================
    # PIN PROTECTION
    # ==================================================

    def set_pin(self, pin: str):
        """Dat PIN moi (luu hash)."""
        pin_hash = hashlib.sha256(pin.encode()).hexdigest()
        self.config["pin_hash"] = pin_hash
        self.config["pin_enabled"] = True
        self._save_config()
        logger.info("Da dat PIN bao mat moi.")

    def verify_pin(self, pin: str, chat_id: int) -> bool:
        """Xac nhan PIN. Neu dung -> cho phep trong 15 phut."""
        if not self.config["pin_enabled"]:
            return True

        pin_hash = hashlib.sha256(pin.encode()).hexdigest()
        if pin_hash == self.config["pin_hash"]:
            self._pin_verified[str(chat_id)] = time.time()
            self._log_audit(chat_id, "pin_verified", "PIN xac nhan thanh cong")
            return True
        else:
            self._log_audit(chat_id, "pin_failed", "Nhap PIN sai")
            return False

    def is_pin_verified(self, chat_id: int) -> bool:
        """Kiem tra PIN da xac nhan chua (con hieu luc 15 phut)."""
        if not self.config["pin_enabled"]:
            return True

        key = str(chat_id)
        if key not in self._pin_verified:
            return False

        elapsed = time.time() - self._pin_verified[key]
        return elapsed < 900  # 15 phut

    def requires_pin(self, action: str) -> bool:
        """Kiem tra lenh nay co can PIN khong."""
        if not self.config["pin_enabled"]:
            return False
        return action in self.config["pin_required_for"]

    # ==================================================
    # TRANSACTION LIMITS
    # ==================================================

    def check_tx_limit(self, chat_id: int, amount: float) -> dict:
        """Kiem tra gioi han giao dich."""
        if not self.config["tx_limit_enabled"]:
            return {"allowed": True}

        # Gioi han moi giao dich
        max_per_tx = self.config["tx_limit_per_tx"]
        if amount > max_per_tx:
            return {
                "allowed": False,
                "reason": f"Vuot gioi han: {amount} > {max_per_tx} ETH/tx. Dung /setlimit de thay doi.",
            }

        # Gioi han hang ngay
        key = str(chat_id)
        now = time.time()
        today_start = now - 86400

        if key not in self._tx_tracker:
            self._tx_tracker[key] = []

        # Loc chi giu giao dich trong 24h
        self._tx_tracker[key] = [
            tx for tx in self._tx_tracker[key]
            if tx["time"] > today_start
        ]

        daily_total = sum(tx["amount"] for tx in self._tx_tracker[key])
        max_daily = self.config["tx_limit_daily"]

        if daily_total + amount > max_daily:
            return {
                "allowed": False,
                "reason": f"Vuot gioi han ngay: da dung {daily_total:.4f}/{max_daily} ETH. Reset sau 24h.",
            }

        return {"allowed": True}

    def record_tx(self, chat_id: int, amount: float, tx_type: str):
        """Ghi nhan 1 giao dich."""
        key = str(chat_id)
        if key not in self._tx_tracker:
            self._tx_tracker[key] = []
        self._tx_tracker[key].append({
            "amount": amount,
            "type": tx_type,
            "time": time.time(),
        })
        self._log_audit(chat_id, tx_type, f"Amount: {amount} ETH")

    # ==================================================
    # RATE LIMITING
    # ==================================================

    def check_rate_limit(self, chat_id: int) -> bool:
        """Kiem tra rate limit (chong spam lenh)."""
        if not self.config["rate_limit_enabled"]:
            return True

        key = str(chat_id)
        now = time.time()
        window = 60  # 1 phut

        if key not in self._rate_tracker:
            self._rate_tracker[key] = []

        # Loc chi giu request trong 1 phut
        self._rate_tracker[key] = [
            t for t in self._rate_tracker[key]
            if t > now - window
        ]

        max_commands = self.config["rate_limit_commands"]
        if len(self._rate_tracker[key]) >= max_commands:
            return False

        self._rate_tracker[key].append(now)
        self._last_activity[str(chat_id)] = now
        return True

    # ==================================================
    # HONEYPOT DETECTION
    # ==================================================

    async def check_honeypot(self, token_address: str, chain: str = "ethereum") -> dict:
        """
        Kiem tra token co phai honeypot/scam khong.
        Su dung honeypot.is API (free).
        """
        import aiohttp

        chain_map = {
            "ethereum": "eth", "bsc": "bsc2", "polygon": "polygon",
            "arbitrum": "arbitrum", "base": "base", "optimism": "optimism",
            "avalanche": "avalanche", "fantom": "fantom", "linea": "linea",
        }
        api_chain = chain_map.get(chain, "eth")

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"https://api.honeypot.is/v2/IsHoneypot?address={token_address}&chainID={api_chain}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        is_honeypot = data.get("honeypotResult", {}).get("isHoneypot", False)
                        tax_buy = data.get("simulationResult", {}).get("buyTax", 0) or 0
                        tax_sell = data.get("simulationResult", {}).get("sellTax", 0) or 0

                        warnings = []
                        safe = True

                        if is_honeypot:
                            warnings.append("HONEYPOT! Khong the ban token sau khi mua")
                            safe = False

                        if tax_buy > 10:
                            warnings.append(f"Thue mua cao: {tax_buy:.1f}%")
                            if tax_buy > 50:
                                safe = False

                        if tax_sell > 10:
                            warnings.append(f"Thue ban cao: {tax_sell:.1f}%")
                            if tax_sell > 50:
                                safe = False

                        if tax_sell > 90:
                            warnings.append("Thue ban >90%: CO THE LA SCAM!")
                            safe = False

                        return {
                            "is_honeypot": is_honeypot,
                            "buy_tax": tax_buy,
                            "sell_tax": tax_sell,
                            "safe": safe,
                            "warnings": warnings,
                            "checked": True,
                        }

        except Exception as e:
            logger.error(f"Honeypot check error: {e}")

        return {"checked": False, "safe": True, "warnings": ["Khong kiem tra duoc honeypot"]}

    # ==================================================
    # AUDIT LOG
    # ==================================================

    def _log_audit(self, chat_id: int, action: str, detail: str = ""):
        """Ghi log hanh dong."""
        entry = {
            "time": datetime.now().isoformat(),
            "chat_id": chat_id,
            "action": action,
            "detail": detail,
        }

        try:
            logs = []
            if AUDIT_LOG.exists():
                with open(AUDIT_LOG, "r") as f:
                    logs = json.load(f)

            logs.append(entry)
            # Giu toi da 1000 dong
            if len(logs) > 1000:
                logs = logs[-1000:]

            with open(AUDIT_LOG, "w") as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_audit_log(self, limit: int = 20) -> list[dict]:
        """Doc audit log."""
        try:
            if AUDIT_LOG.exists():
                with open(AUDIT_LOG, "r") as f:
                    logs = json.load(f)
                return logs[-limit:]
        except Exception:
            pass
        return []

    # ==================================================
    # MIDDLEWARE (Kiem tra toan bo truoc khi xu ly lenh)
    # ==================================================

    def check_access(self, chat_id: int, action: str = "general") -> dict:
        """
        Kiem tra tong the truoc khi cho phep thuc hien lenh.
        Tra ve {"allowed": True} hoac {"allowed": False, "reason": "..."}
        """
        # 1. Whitelist
        if not self.is_whitelisted(chat_id):
            return {"allowed": False, "reason": "Ban khong co quyen su dung bot nay. Lien he admin."}

        # 2. Rate limit
        if not self.check_rate_limit(chat_id):
            return {"allowed": False, "reason": "Qua nhieu lenh! Cho 1 phut roi thu lai."}

        # 3. PIN cho giao dich
        if self.requires_pin(action) and not self.is_pin_verified(chat_id):
            return {
                "allowed": False,
                "reason": f"Lenh /{action} can xac nhan PIN.\nGo: /pin [ma PIN] de mo khoa (hieu luc 15 phut).",
                "need_pin": True,
            }

        # Update last activity
        self._last_activity[str(chat_id)] = time.time()
        self._log_audit(chat_id, action)

        return {"allowed": True}

    def get_security_status(self) -> dict:
        """Tra ve trang thai bao mat hien tai."""
        return {
            "whitelist": self.config["whitelist_enabled"],
            "whitelist_count": len(self.config["whitelist_ids"]),
            "pin_enabled": self.config["pin_enabled"],
            "tx_limit": f"{self.config['tx_limit_per_tx']} ETH/tx, {self.config['tx_limit_daily']} ETH/ngay",
            "rate_limit": f"{self.config['rate_limit_commands']} cmd/phut",
            "honeypot_check": self.config["honeypot_check"],
        }
