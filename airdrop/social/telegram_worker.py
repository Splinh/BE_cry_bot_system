"""
Telegram Worker - Dieu khien hang loat account Telegram de cay Airdrop.
- Dang nhap nhieu Session (tai khoan) bang API_ID & API_HASH.
- Ho tro gan Proxy vao tung Session.
- Tu dong Join Channel, Nhan file, Tuong tac Bot (Mini App).
"""
import os
import asyncio
from loguru import logger
from typing import Optional

# Pyrogram la thu vien de dung Telegram Client API (User API), ko phai Bot API
try:
    from pyrogram import Client
    from pyrogram.errors import FloodWait, UserDeactivatedBan, SessionPasswordNeeded
except ImportError:
    # Cai dat tam thoi neu may tinh chua co pyrogram: pip install pyrogram tgcrypto
    pass


class TelegramWorker:
    """
    Quan ly va dieu khien cac tai khoan Telegram (Session).
    Moi instance ung voi 1 Session (1 Sdt Telegram).
    """

    def __init__(self, session_name: str, api_id: int, api_hash: str, proxy: dict = None, work_dir: str = "data/sessions"):
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.proxy = proxy
        self.work_dir = work_dir
        
        os.makedirs(self.work_dir, exist_ok=True)
        
        # Khai bao client Pyrogram
        try:
            self.app = Client(
                name=self.session_name,
                api_id=self.api_id,
                api_hash=self.api_hash,
                workdir=self.work_dir,
                proxy=self.proxy
            )
        except Exception as e:
            logger.error(f"Loi khoi tao Telegram Client [{session_name}]: {e}")
            self.app = None

    async def start(self) -> bool:
        """Thu ket noi va khoi dong session."""
        if not self.app:
            return False
            
        try:
            await self.app.connect()
            logger.success(f"[{self.session_name}] Ket noi Telegram thanh cong.")
            return True
        except Exception as e:
            logger.error(f"[{self.session_name}] Ket noi that bai: {e}")
            return False

    async def join_channel(self, invite_link_or_username: str) -> bool:
        """Tu dong Join vao Group hoac Channel."""
        if not self.app.is_connected:
            await self.start()
            
        try:
            logger.info(f"[{self.session_name}] Dang join: {invite_link_or_username}...")
            await self.app.join_chat(invite_link_or_username)
            logger.success(f"[{self.session_name}] Join thanh cong: {invite_link_or_username}")
            return True
        except FloodWait as e:
            logger.warning(f"[{self.session_name}] Bi Rate Limit (FloodWait)! Doi {e.value} giay...")
            await asyncio.sleep(e.value)
            return await self.join_channel(invite_link_or_username) # Thu lai sau khi doi
        except Exception as e:
            logger.error(f"[{self.session_name}] Loi join channel: {e}")
            return False

    async def interact_with_bot(self, bot_username: str, command: str = "/start") -> bool:
        """Gui lenh den bot (Mini App) de kich hoat Airdrop."""
        if not self.app.is_connected:
            await self.start()
            
        try:
            logger.info(f"[{self.session_name}] Gui {command} cho bot {bot_username}...")
            await self.app.send_message(bot_username, command)
            logger.success(f"[{self.session_name}] Tuong tac bot thanh cong!")
            return True
        except Exception as e:
            logger.error(f"[{self.session_name}] Loi tuong tac bot: {e}")
            return False

    async def stop(self):
        """Dong ket noi."""
        if self.app and self.app.is_connected:
            await self.app.disconnect()
            logger.info(f"[{self.session_name}] Da ngat ket noi.")

    # --- Quan ly danh sach Account tong ---

class TelegramManager:
    """Nhom quan ly nhieu Worker cung luc."""
    
    def __init__(self):
        self.workers: dict[str, TelegramWorker] = {}
        
    def add_account(self, session_name: str, api_id: int, api_hash: str, proxy: dict = None):
        """Them 1 tai khoan vao quan ly."""
        worker = TelegramWorker(session_name, api_id, api_hash, proxy)
        self.workers[session_name] = worker
        logger.info(f"Da them account: {session_name} vao TelegramManager.")

    async def join_all(self, channel_url: str):
        """Dieu doan tat ca tai khoan cung Join vao 1 Channel (Cay refs / Zealy)."""
        logger.info(f"Yeu cau {len(self.workers)} tai khoan JOIN {channel_url}")
        for name, worker in self.workers.items():
            success = await worker.join_channel(channel_url)
            # Nghi 5-10s giua moi tai khoan de chong bi Telegram quet Spam IP
            if success:
                await asyncio.sleep(5)
            
    async def claim_all_bots(self, bot_username: str, command: str):
        """Tat ca acc gui lenh vao Tap-to-earn bot."""
        logger.info(f"Yeu cau {len(self.workers)} tai khoan CLAIM {bot_username}")
        for name, worker in self.workers.items():
            await worker.interact_with_bot(bot_username, command)
            await asyncio.sleep(3)

    async def shutdown(self):
        """Dong tat ca account khi tat tool."""
        for worker in self.workers.values():
            await worker.stop()
