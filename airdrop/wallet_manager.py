"""
Wallet Manager - Tao, quan ly va bao mat vi EVM hang loat.
Luu private key duoc ma hoa (Fernet) vao file JSON.
"""
import json
import os
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional

from eth_account import Account
from cryptography.fernet import Fernet
from loguru import logger

from core.config import Config

# Thu muc luu du lieu vi (ma hoa)
WALLETS_DIR = Path(__file__).resolve().parent.parent / "data" / "wallets"
WALLETS_DIR.mkdir(parents=True, exist_ok=True)
KEY_FILE = WALLETS_DIR / "encryption.key"
WALLETS_FILE = WALLETS_DIR / "wallets.json.enc"


class WalletManager:
    """
    Quan ly vi EVM (Ethereum, BSC, Polygon, Arbitrum, zkSync, Base...):
    - Tao vi moi (batch)
    - Ma hoa private key bang Fernet
    - Xuat/nhap vi
    - Kiem tra so du
    """

    def __init__(self):
        self.cipher = self._get_cipher()
        self.wallets: list[dict] = self._load_wallets()

    def _get_cipher(self) -> Fernet:
        """Tao hoac doc encryption key."""
        if KEY_FILE.exists():
            key = KEY_FILE.read_bytes()
        else:
            key = Fernet.generate_key()
            KEY_FILE.write_bytes(key)
            logger.info("Da tao encryption key moi.")
        return Fernet(key)

    def _encrypt(self, data: str) -> str:
        return self.cipher.encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        return self.cipher.decrypt(data.encode()).decode()

    def _load_wallets(self) -> list[dict]:
        """Doc danh sach vi tu file ma hoa."""
        if not WALLETS_FILE.exists():
            return []
        try:
            encrypted = WALLETS_FILE.read_text()
            decrypted = self._decrypt(encrypted)
            return json.loads(decrypted)
        except Exception as e:
            logger.error(f"Loi doc file vi: {e}")
            return []

    def _save_wallets(self):
        """Luu danh sach vi (ma hoa) ra file."""
        data = json.dumps(self.wallets, indent=2)
        encrypted = self._encrypt(data)
        WALLETS_FILE.write_text(encrypted)

    def create_wallet(self, label: str = "") -> dict:
        """Tao 1 vi EVM moi."""
        account = Account.create(extra_entropy=secrets.token_hex(32))

        wallet = {
            "id": len(self.wallets) + 1,
            "label": label or f"Wallet_{len(self.wallets) + 1}",
            "address": account.address,
            "private_key": account.key.hex(),
            "created_at": datetime.now().isoformat(),
            "networks_used": [],
            "tx_count": 0,
            "notes": "",
        }

        self.wallets.append(wallet)
        self._save_wallets()

        logger.success(f"Da tao vi #{wallet['id']}: {account.address}")
        return wallet

    def create_batch(self, count: int = 10, prefix: str = "Airdrop") -> list[dict]:
        """Tao nhieu vi cung luc."""
        created = []
        for i in range(count):
            label = f"{prefix}_{len(self.wallets) + 1}"
            wallet = self.create_wallet(label)
            created.append(wallet)
        logger.info(f"Da tao {count} vi moi (tong: {len(self.wallets)})")
        return created

    def list_wallets(self, show_keys: bool = False) -> list[dict]:
        """Liet ke tat ca vi (an private key mac dinh)."""
        result = []
        for w in self.wallets:
            info = {
                "id": w["id"],
                "label": w["label"],
                "address": w["address"],
                "tx_count": w["tx_count"],
                "networks": w.get("networks_used", []),
            }
            if show_keys:
                info["private_key"] = w["private_key"]
            result.append(info)
        return result

    def get_wallet(self, wallet_id: int) -> Optional[dict]:
        """Lay thong tin 1 vi theo ID."""
        for w in self.wallets:
            if w["id"] == wallet_id:
                return w
        return None

    def get_private_key(self, wallet_id: int) -> Optional[str]:
        """Lay private key cua 1 vi."""
        w = self.get_wallet(wallet_id)
        return w["private_key"] if w else None

    def update_tx_count(self, wallet_id: int, network: str = ""):
        """Cap nhat so luong giao dich cua vi."""
        for w in self.wallets:
            if w["id"] == wallet_id:
                w["tx_count"] += 1
                if network and network not in w.get("networks_used", []):
                    w.setdefault("networks_used", []).append(network)
                self._save_wallets()
                return

    def export_addresses(self) -> str:
        """Xuat danh sach dia chi vi (de nap gas tu san)."""
        lines = []
        for w in self.wallets:
            lines.append(f"{w['label']}: {w['address']}")
        return "\n".join(lines)

    def get_summary(self) -> dict:
        """Thong ke tong quan."""
        total = len(self.wallets)
        active = sum(1 for w in self.wallets if w.get("tx_count", 0) > 0)
        total_tx = sum(w.get("tx_count", 0) for w in self.wallets)
        return {
            "total_wallets": total,
            "active_wallets": active,
            "inactive_wallets": total - active,
            "total_transactions": total_tx,
        }
