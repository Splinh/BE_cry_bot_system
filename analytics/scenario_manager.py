"""
Scenario Manager Module - Quản lý kịch bản giao dịch và Tự động Khớp lệnh (Auto-Trade).
Hệ thống theo dõi các mốc chiến lược thay vì spam tín hiệu máy móc.
"""
import os
import json
import time
from datetime import datetime
from loguru import logger
from typing import Dict, List, Optional

from core.config import Config
from notifiers.telegram_bot import TelegramNotifier
from notifiers.zalo_bot import ZaloNotifier

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scenarios.json")

class ScenarioManager:
    def __init__(self, trade_engine=None, signal_tracker=None):
        self.trade_engine = trade_engine
        self.signal_tracker = signal_tracker
        self.tg = TelegramNotifier()
        self.za = ZaloNotifier()
        self.last_early_alerts = {}
        self.scenarios: Dict[str, dict] = {}
        self.load_scenarios()

    def load_scenarios(self):
        """Đọc danh sách kịch bản từ file JSON. Nếu chưa có, tạo kịch bản mặc định."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.scenarios = json.load(f)
                    return
            except Exception as e:
                logger.error(f"Lỗi đọc scenarios.json: {e}")

        # Khởi tạo kịch bản mặc định BTC hôm nay
        self.scenarios = {
            "BTC_SHORT_OCT03": {
                "id": "BTC_SHORT_OCT03",
                "coin": "BTC",
                "direction": "SHORT",
                "trigger_price": 85300.0,
                "early_warning_price": 84800.0,
                "sl": 86250.0,
                "tp1": 84000.0,
                "tp2": 83000.0,
                "tp3": 82000.0,
                "leverage": 10,
                "auto_trade": True,
                "status": "ACTIVE",
                "description": "Canh Short vùng cản S-R Flip 85,300$ - 85,600$ sau nhịp hồi kỹ thuật.",
                "created_at": datetime.now().isoformat()
            },
            "BTC_LONG_OCT03": {
                "id": "BTC_LONG_OCT03",
                "coin": "BTC",
                "direction": "LONG",
                "trigger_price": 84100.0,
                "early_warning_price": 84450.0,
                "sl": 83300.0,
                "tp1": 85000.0,
                "tp2": 85500.0,
                "tp3": 86000.0,
                "leverage": 10,
                "auto_trade": True,
                "status": "ACTIVE",
                "description": "Canh Scalp Long vùng hỗ trợ 83,800$ - 84,100$ khi giá quét đáy rút chân.",
                "created_at": datetime.now().isoformat()
            }
        }
        self.save_scenarios()

    def save_scenarios(self):
        """Lưu danh sách kịch bản ra file JSON."""
        try:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.scenarios, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Lỗi lưu scenarios.json: {e}")

    def get_active_scenarios(self) -> List[dict]:
        return [s for s in self.scenarios.values() if s.get("status") == "ACTIVE"]

    def set_auto_trade(self, scenario_id: str, enabled: bool) -> bool:
        if scenario_id in self.scenarios:
            self.scenarios[scenario_id]["auto_trade"] = enabled
            self.save_scenarios()
            return True
        return False

    def toggle_global_auto_trade(self, enabled: bool):
        for s in self.scenarios.values():
            s["auto_trade"] = enabled
        self.save_scenarios()

    async def broadcast(self, message: str):
        """Gửi thông báo về Telegram và Zalo."""
        try:
            await self.tg.send_message(message)
        except Exception as e:
            logger.error(f"Lỗi gửi Telegram: {e}")
        try:
            await self.za.send_message(message)
        except Exception as e:
            logger.error(f"Lỗi gửi Zalo: {e}")

    async def check_price(self, coin: str, current_price: float):
        """
        Kiểm tra giá hiện tại với các kịch bản đang active.
        Tự động cảnh báo sớm và tự động vào lệnh khi chạm điểm kích hoạt.
        """
        if current_price <= 0:
            return

        now = time.time()
        for sc_id, sc in list(self.scenarios.items()):
            if sc.get("status") != "ACTIVE":
                continue
            if sc.get("coin", "").upper() != coin.upper():
                continue

            direction = sc.get("direction", "SHORT").upper()
            trigger_price = float(sc.get("trigger_price", 0))
            early_price = float(sc.get("early_warning_price", 0))
            is_auto = sc.get("auto_trade", True) and Config.SCENARIO_AUTO_TRADE

            # 1. KIỂM TRA ĐIỀU KIỆN KÍCH HOẠT VÀO LỆNH (TRIGGER ZONE)
            is_triggered = False
            if direction == "SHORT" and current_price >= trigger_price:
                is_triggered = True
            elif direction == "LONG" and current_price <= trigger_price:
                is_triggered = True

            if is_triggered:
                # Đánh dấu đã kích hoạt
                sc["status"] = "EXECUTED" if is_auto else "TRIGGERED"
                sc["executed_price"] = current_price
                sc["executed_at"] = datetime.now().isoformat()
                self.save_scenarios()

                logger.warning(f"🎯 KỊCH BẢN KÍCH HOẠT: {sc_id} | {direction} tại ${current_price:,.2f}")

                # Thực hiện AUTO TRADE nếu được bật
                trade_executed = False
                if is_auto:
                    try:
                        signal_payload = {
                            "key": f"{sc_id}_{int(now)}",
                            "coin": coin,
                            "type": "FUTURES",
                            "direction": direction,
                            "entry": current_price,
                            "sl": sc.get("sl"),
                            "tp1": sc.get("tp1"),
                            "tp2": sc.get("tp2"),
                            "tp3": sc.get("tp3", sc.get("tp2")),
                            "leverage": sc.get("leverage", 10),
                            "rating": 5,
                            "tf": "Scenario",
                            "reason": sc.get("description", "Vào lệnh tự động theo Kịch bản chiến lược"),
                        }
                        if self.signal_tracker:
                            self.signal_tracker.add_signal(signal_payload)
                            trade_executed = True
                        elif self.trade_engine:
                            self.trade_engine.open_position(signal_payload)
                            trade_executed = True
                        logger.success(f"✅ [Auto Trade] Đã tự động mở vị thế cho {sc_id}")
                    except Exception as te_err:
                        logger.error(f"❌ Lỗi tự động mở vị thế: {te_err}")

                # Bắn thông báo tới Telegram & Zalo
                action_text = "ĐÃ TỰ ĐỘNG KHỚP LỆNH (AUTO-TRADE)" if trade_executed else "ĐÃ CHẠM VÙNG VÀO LỆNH"
                icon = "🔴" if direction == "SHORT" else "🟢"
                msg = (
                    f"{icon} <b>[{action_text}]</b>\n\n"
                    f"🎯 <b>Kịch bản:</b> {sc_id} ({direction} {coin})\n"
                    f"💰 <b>Giá khớp/kích hoạt:</b> <code>${current_price:,.2f}</code>\n"
                    f"📍 <b>Khu vực:</b> <code>${trigger_price:,.2f}</code>\n"
                    f"🛑 <b>Stop Loss (SL):</b> <code>${sc.get('sl'):,.2f}</code>\n"
                    f"🎯 <b>Take Profit (TP1):</b> <code>${sc.get('tp1'):,.2f}</code> | <b>(TP2):</b> <code>${sc.get('tp2'):,.2f}</code>\n"
                    f"🛡️ <b>Đòn bẩy:</b> {sc.get('leverage', 10)}x\n"
                    f"💡 <b>Kế hoạch:</b> {sc.get('description', '')}\n\n"
                    f"<i>{'Hệ thống đang tự động quản lý PnL và chốt lời/cắt lỗ.' if trade_executed else 'Vui lòng kiểm tra và xác nhận vị thế!'}</i>"
                )
                await self.broadcast(msg)
                continue

            # 2. KIỂM TRA CẢNH BÁO SỚM (EARLY WARNING)
            is_early = False
            if direction == "SHORT" and early_price > 0 and current_price >= early_price:
                is_early = True
            elif direction == "LONG" and early_price > 0 and current_price <= early_price:
                is_early = True

            if is_early:
                last_time = self.last_early_alerts.get(sc_id, 0)
                # Cooldown 10 phút cho cảnh báo sớm
                if now - last_time > 600:
                    self.last_early_alerts[sc_id] = now
                    arrow = "tiến lên cản" if direction == "SHORT" else "trượt về hỗ trợ"
                    msg = (
                        f"⚠️ <b>[CẢNH BÁO SỚM KỊCH BẢN]</b>\n\n"
                        f"🪙 <b>{coin}</b> đang {arrow}: <code>${current_price:,.2f}</code>\n"
                        f"🎯 <b>Kịch bản phục kích:</b> {sc_id} ({direction})\n"
                        f"📍 <b>Mốc kích hoạt:</b> <code>${trigger_price:,.2f}</code> (cách {abs(trigger_price - current_price):,.1f}$)\n"
                        f"⚡ <b>Chế độ Auto-Trade:</b> {'BẬT (sẽ tự động vào lệnh khi chạm mốc)' if is_auto else 'TẮT (thông báo thủ công)'}"
                    )
                    await self.broadcast(msg)

    def format_status_message(self, current_btc_price: float = 0.0) -> str:
        """Tạo tin nhắn báo cáo trạng thái các kịch bản cho lệnh Telegram /scenario."""
        actives = self.get_active_scenarios()
        lines = [
            "📋 <b>DANH SÁCH KỊCH BẢN GIAO DỊCH HIỆN TẠI</b>",
            f"💵 <b>Giá BTC hiện tại:</b> <code>${current_btc_price:,.2f}</code>\n" if current_btc_price > 0 else "",
            f"⚙️ <b>Auto-Trade hệ thống:</b> {'🟢 BẬT' if Config.SCENARIO_AUTO_TRADE else '🔴 TẮT'}\n",
        ]
        if not actives:
            lines.append("<i>Hiện không có kịch bản nào đang chờ. Bạn có thể thêm kịch bản mới!</i>")
            return "\n".join(lines)

        for sc in actives:
            direction = sc.get("direction", "SHORT")
            icon = "🔴" if direction == "SHORT" else "🟢"
            trigger = float(sc.get("trigger_price", 0))
            diff_text = ""
            if current_btc_price > 0:
                diff = trigger - current_btc_price
                diff_text = f" (cách {abs(diff):,.1f}$)"
            
            auto_icon = "🤖 Auto" if sc.get("auto_trade", True) else "👤 Thủ công"
            lines.append(
                f"{icon} <b>{sc['id']}</b> ({direction} {sc['coin']}) - {auto_icon}\n"
                f"   • Vùng kích hoạt: <code>${trigger:,.2f}</code>{diff_text}\n"
                f"   • SL: <code>${sc.get('sl'):,.2f}</code> | TP1: <code>${sc.get('tp1'):,.2f}</code>\n"
                f"   • Ghi chú: {sc.get('description', '')}\n"
            )

        lines.append("💡 <i>Gõ <code>/scenario auto on</code> hoặc <code>/scenario auto off</code> để bật/tắt tự động vào lệnh.</i>")
        return "\n".join(lines)
