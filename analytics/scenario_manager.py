"""
Scenario Manager Module - Quản lý kịch bản giao dịch và Tự động Khớp lệnh (Auto-Trade).
Hệ thống theo dõi các mốc chiến lược thay vì spam tín hiệu máy móc.
"""
import os
import json
import time
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, List, Optional

from core.config import Config
from notifiers.telegram_bot import TelegramNotifier
from notifiers.zalo_bot import ZaloNotifier

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scenarios.json")

# Số ngày giữ lại lịch sử kịch bản đã đóng (EXPIRED/REPLACED/CANCELLED/EXECUTED...) trong file JSON
HISTORY_KEEP_DAYS = 7


class ScenarioManager:
    def __init__(self, trade_engine=None, signal_tracker=None):
        self.trade_engine = trade_engine
        self.signal_tracker = signal_tracker
        self.tg = TelegramNotifier()
        self.za = ZaloNotifier()
        self.last_early_alerts = {}
        self.scenarios: Dict[str, dict] = {}
        self._file_mtime: float = 0.0
        self.load_scenarios()

    # ------------------------------------------------------------------
    # Lưu trữ & đồng bộ file
    # ------------------------------------------------------------------
    @staticmethod
    def _get_file_mtime() -> float:
        try:
            return os.path.getmtime(DATA_FILE)
        except OSError:
            return 0.0

    def load_scenarios(self):
        """Đọc danh sách kịch bản từ file JSON. Chưa có file -> danh sách rỗng (dùng /scenario gen để tạo)."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.scenarios = data if isinstance(data, dict) else {}
                self._file_mtime = self._get_file_mtime()
                return
            except Exception as e:
                logger.error(f"Lỗi đọc scenarios.json: {e}")
        self.scenarios = {}

    def _reload_if_changed(self):
        """
        Đọc lại file nếu có instance khác vừa ghi (vd: lệnh /scenario gen chạy song song với watcher).
        Tránh việc watcher giữ bản cũ trong RAM rồi ghi đè mất kịch bản mới.
        """
        mtime = self._get_file_mtime()
        if not mtime or mtime == self._file_mtime:
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.scenarios = data
                self._file_mtime = mtime
        except Exception as e:
            # File có thể đang được ghi dở -> lần kiểm tra sau sẽ đọc lại
            logger.debug(f"Chưa đọc lại được scenarios.json: {e}")

    def save_scenarios(self):
        """Lưu danh sách kịch bản ra file JSON (ghi atomic qua file tạm để không bao giờ bị đọc dở)."""
        try:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            tmp_path = f"{DATA_FILE}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.scenarios, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, DATA_FILE)
            self._file_mtime = self._get_file_mtime()
        except Exception as e:
            logger.error(f"Lỗi lưu scenarios.json: {e}")

    # ------------------------------------------------------------------
    # Vòng đời kịch bản: hết hạn / thay thế / hủy
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_iso_ts(value) -> float:
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(str(value)).timestamp()
        except (TypeError, ValueError):
            return 0.0

    def _get_expiry_ts(self, sc: dict) -> float:
        """Thời điểm hết hạn: ưu tiên expires_at, nếu không có thì created_at + SCENARIO_TTL_HOURS."""
        exp = self._parse_iso_ts(sc.get("expires_at"))
        if exp:
            return exp
        created = self._parse_iso_ts(sc.get("created_at"))
        if created:
            return created + Config.SCENARIO_TTL_HOURS * 3600
        return 0.0

    def _close(self, sc: dict, status: str, reason: str):
        sc["status"] = status
        sc["closed_at"] = datetime.now().isoformat()
        sc["close_reason"] = reason

    def _expire_stale(self) -> List[str]:
        """Đóng các kịch bản ACTIVE đã quá hạn hiệu lực. Trả về danh sách ID vừa hết hạn."""
        now_ts = time.time()
        expired = []
        for sc_id, sc in self.scenarios.items():
            if sc.get("status") != "ACTIVE":
                continue
            exp = self._get_expiry_ts(sc)
            if exp and now_ts >= exp:
                self._close(sc, "EXPIRED", "Hết thời gian hiệu lực")
                expired.append(sc_id)
        if expired:
            self.save_scenarios()
            logger.info(f"⌛ Kịch bản hết hạn: {', '.join(expired)}")
        return expired

    def _prune_history(self):
        """Xóa khỏi file các kịch bản đã đóng quá HISTORY_KEEP_DAYS ngày để file không phình to."""
        cutoff = time.time() - HISTORY_KEEP_DAYS * 86400
        self.scenarios = {
            k: v for k, v in self.scenarios.items()
            if v.get("status") == "ACTIVE"
            or (self._parse_iso_ts(v.get("closed_at") or v.get("executed_at") or v.get("created_at")) or time.time()) >= cutoff
        }

    def cancel_scenario(self, scenario_id: str, reason: str = "Hủy thủ công") -> bool:
        """Hủy 1 kịch bản ACTIVE theo ID (không phân biệt hoa thường)."""
        self._reload_if_changed()
        target = next((k for k in self.scenarios if k.upper() == scenario_id.upper()), None)
        if not target or self.scenarios[target].get("status") != "ACTIVE":
            return False
        self._close(self.scenarios[target], "CANCELLED", reason)
        self.save_scenarios()
        return True

    def cancel_all(self, coin: Optional[str] = None, reason: str = "Hủy thủ công") -> List[str]:
        """Hủy toàn bộ kịch bản ACTIVE (hoặc chỉ của 1 coin). Trả về danh sách ID đã hủy."""
        self._reload_if_changed()
        cancelled = []
        for sc_id, sc in self.scenarios.items():
            if sc.get("status") != "ACTIVE":
                continue
            if coin and sc.get("coin", "").upper() != coin.upper():
                continue
            self._close(sc, "CANCELLED", reason)
            cancelled.append(sc_id)
        if cancelled:
            self.save_scenarios()
        return cancelled

    def get_active_scenarios(self) -> List[dict]:
        self._reload_if_changed()
        self._expire_stale()
        return [s for s in self.scenarios.values() if s.get("status") == "ACTIVE"]

    def set_auto_trade(self, scenario_id: str, enabled: bool) -> bool:
        self._reload_if_changed()
        if scenario_id in self.scenarios:
            self.scenarios[scenario_id]["auto_trade"] = enabled
            self.save_scenarios()
            return True
        return False

    def toggle_global_auto_trade(self, enabled: bool):
        self._reload_if_changed()
        for s in self.scenarios.values():
            s["auto_trade"] = enabled
        self.save_scenarios()

    def calculate_alert_step(self, coin: str, trigger_price: float, early_price: float) -> float:
        """
        Tính bước giá tối thiểu để gửi cảnh báo nấc tiếp theo.
        Tránh lặp thông báo khi giá chỉ dao động nhỏ tại cùng một vùng.
        """
        diff = abs(trigger_price - early_price)
        coin_up = coin.upper()
        if coin_up == "BTC":
            # Với BTC, bước giá chuẩn $100 hoặc 1/4 khoảng cách nếu khoảng cách lớn hơn
            return max(100.0, round(diff / 4.0, 0)) if diff >= 400 else 100.0
        elif coin_up == "ETH":
            return max(10.0, round(diff / 4.0, 0)) if diff >= 40 else 10.0
        elif coin_up == "SOL":
            return max(1.0, round(diff / 4.0, 1)) if diff >= 4 else 1.0
        else:
            return max(round(trigger_price * 0.002, 4), round(diff / 4.0, 4))

    async def broadcast(self, message: str, to_group: bool = True):
        """
        Gửi thông báo về Telegram và Zalo.
        to_group=True: Gửi cả cá nhân (Bot) và Nhóm (Group). Dùng cho kịch bản kích hoạt/khớp lệnh.
        to_group=False: Chỉ gửi trong Bot cá nhân, không spam Group. Dùng cho cảnh báo sớm.
        """
        try:
            await self.tg.send_message(message, to_group=to_group)
        except Exception as e:
            logger.error(f"Lỗi gửi Telegram: {e}")
        try:
            await self.za.send_message(message, to_group=to_group)
        except Exception as e:
            logger.error(f"Lỗi gửi Zalo: {e}")

    async def check_price(self, coin: str, current_price: float):
        """
        Kiểm tra giá hiện tại với các kịch bản đang active.
        Tự động cảnh báo sớm theo từng nấc giá (step) và tự động vào lệnh khi chạm điểm kích hoạt.
        """
        if current_price <= 0:
            return

        now = time.time()

        # Đồng bộ với file (nhận kịch bản mới từ /scenario gen) và đóng kịch bản quá hạn
        self._reload_if_changed()
        expired_ids = self._expire_stale()
        if expired_ids:
            await self.broadcast(
                "⌛ <b>Kịch bản hết hiệu lực</b>: " + ", ".join(expired_ids)
                + "\n<i>Gõ /scenario gen để lên kịch bản mới theo giá hiện tại.</i>",
                to_group=False,
            )

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

                # Bắn thông báo kịch bản tới CẢ GROUP VÀ BOT (to_group=True)
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
                await self.broadcast(msg, to_group=True)
                continue

            # 2. KIỂM TRA CẢNH BÁO SỚM THEO NẤC GIÁ (STEP-BASED MILESTONE ALERT)
            if direction == "SHORT":
                in_early_zone = (early_price > 0 and current_price >= early_price and current_price < trigger_price)
            else:  # LONG
                in_early_zone = (early_price > 0 and current_price <= early_price and current_price > trigger_price)

            if in_early_zone:
                step = float(sc.get("alert_step") or self.calculate_alert_step(coin, trigger_price, early_price))
                last_price = float(sc.get("last_alert_price", 0.0))
                last_time = float(sc.get("last_alert_time", 0.0))
                alert_count = int(sc.get("alert_count", 0))

                should_alert = False
                time_elapsed = now - last_time

                if last_price <= 0:
                    # Lần đầu tiên chạm mốc cảnh báo sớm
                    if time_elapsed >= 60:
                        should_alert = True
                else:
                    # Đã cảnh báo mốc trước: GIÁ PHẢI TIẾN THÊM VỀ PHÍA TRIGGER ĐỦ 1 BƯỚC GIÁ (step)
                    # Và cooldown tối thiểu 60s để tránh giật râu nến liên tục
                    if direction == "SHORT":
                        if current_price >= (last_price + step) and time_elapsed >= 60:
                            should_alert = True
                    elif direction == "LONG":
                        if current_price <= (last_price - step) and time_elapsed >= 60:
                            should_alert = True

                if should_alert:
                    alert_count += 1
                    sc["last_alert_price"] = current_price
                    sc["last_alert_time"] = now
                    sc["alert_count"] = alert_count
                    self.save_scenarios()

                    arrow = "tiến lên cản" if direction == "SHORT" else "trượt về hỗ trợ"
                    next_step_price = (current_price + step) if direction == "SHORT" else (current_price - step)
                    dist = abs(trigger_price - current_price)

                    msg = (
                        f"⚠️ <b>[CẢNH BÁO SỚM KỊCH BẢN]</b> (Nấc #{alert_count})\n\n"
                        f"🪙 <b>{coin}</b> đang {arrow}: <code>${current_price:,.2f}</code>\n"
                        f"🎯 <b>Kịch bản phục kích:</b> {sc_id} ({direction})\n"
                        f"📍 <b>Mốc kích hoạt:</b> <code>${trigger_price:,.2f}</code> (cách {dist:,.1f}$)\n"
                        f"📏 <b>Nấc báo tiếp theo:</b> {'≥' if direction == 'SHORT' else '≤'} <code>${next_step_price:,.2f}</code> (bước {step:,.0f}$)\n"
                        f"⚡ <b>Chế độ Auto-Trade:</b> {'BẬT (sẽ tự động vào lệnh khi chạm mốc)' if is_auto else 'TẮT (thông báo thủ công)'}"
                    )
                    # CHỈ THÔNG BÁO TRONG BOT RIÊNG, KHÔNG GỬI VÀO GROUP!
                    await self.broadcast(msg, to_group=False)
            else:
                # Cơ chế hạ nhiệt: Nếu giá đã rút lui cách xa khỏi vùng cảnh báo sớm > 2*step trong > 30 phút
                last_price = float(sc.get("last_alert_price", 0.0))
                if last_price > 0:
                    step = float(sc.get("alert_step") or self.calculate_alert_step(coin, trigger_price, early_price))
                    if direction == "SHORT" and current_price < (early_price - step * 2):
                        if (now - float(sc.get("last_alert_time", 0.0))) > 1800:
                            sc["last_alert_price"] = 0.0
                            sc["alert_count"] = 0
                            self.save_scenarios()
                    elif direction == "LONG" and current_price > (early_price + step * 2):
                        if (now - float(sc.get("last_alert_time", 0.0))) > 1800:
                            sc["last_alert_price"] = 0.0
                            sc["alert_count"] = 0
                            self.save_scenarios()

    def format_status_message(self, current_btc_price: float = 0.0, prices: dict = None) -> str:
        """Tạo tin nhắn báo cáo trạng thái các kịch bản cho lệnh Telegram /scenario."""
        actives = self.get_active_scenarios()
        lines = [
            "📋 <b>DANH SÁCH KỊCH BẢN GIAO DỊCH HIỆN TẠI</b>",
            f"⚙️ <b>Auto-Trade hệ thống:</b> {'🟢 BẬT' if Config.SCENARIO_AUTO_TRADE else '🔴 TẮT'}\n",
        ]
        if not actives:
            lines.append("<i>Hiện không có kịch bản nào đang chờ. Bạn có thể thêm kịch bản mới!</i>")
            return "\n".join(lines)

        price_map = dict(prices) if prices else {}
        if current_btc_price > 0 and "BTC" not in price_map:
            price_map["BTC"] = current_btc_price

        for sc in actives:
            coin = sc.get("coin", "BTC").upper()
            direction = sc.get("direction", "SHORT")
            icon = "🔴" if direction == "SHORT" else "🟢"
            trigger = float(sc.get("trigger_price", 0))
            diff_text = ""
            ref_price = price_map.get(coin, 0.0)
            if ref_price > 0:
                diff = trigger - ref_price
                diff_text = f" (cách {abs(diff):,.1f}$)"
            
            auto_icon = "🤖 Auto" if sc.get("auto_trade", True) else "👤 Thủ công"
            step = float(sc.get("alert_step") or self.calculate_alert_step(coin, trigger, float(sc.get("early_warning_price", 0))))
            last_p = float(sc.get("last_alert_price", 0))
            last_alert_text = f" | Đã báo mốc: ${last_p:,.2f}" if last_p > 0 else ""
            exp_ts = self._get_expiry_ts(sc)
            exp_text = f"\n   • Hiệu lực đến: {datetime.fromtimestamp(exp_ts).strftime('%H:%M %d/%m')}" if exp_ts else ""
            lines.append(
                f"{icon} <b>{sc['id']}</b> ({direction} {sc['coin']}) - {auto_icon}\n"
                f"   • Vùng kích hoạt: <code>${trigger:,.2f}</code>{diff_text}\n"
                f"   • Cảnh báo sớm: <code>${float(sc.get('early_warning_price', 0)):,.2f}</code> (bước {step:,.0f}${last_alert_text})\n"
                f"   • SL: <code>${sc.get('sl'):,.2f}</code> | TP1: <code>${sc.get('tp1'):,.2f}</code>{exp_text}\n"
                f"   • Ghi chú: {sc.get('description', '')}\n"
            )

        lines.append("⚡ <i>Gõ <code>/scenario gen</code> để phân tích lại và thay thế kịch bản cũ của BTC, ETH, Vàng.</i>")
        lines.append("🗑 <i><code>/scenario del ID</code> hủy 1 kịch bản | <code>/scenario clear</code> hủy tất cả.</i>")
        lines.append("💡 <i><code>/scenario auto on</code> / <code>/scenario auto off</code> bật/tắt tự động vào lệnh.</i>")
        return "\n".join(lines)

    async def auto_generate_scenarios(self, coins: List[str] = None, replace: bool = False) -> Dict[str, dict]:
        """
        Tự động phân tích kỹ thuật và sinh kịch bản chiến lược (BTC, ETH, PAXG Vàng).
        Nếu replace=True: đóng (REPLACED) các kịch bản ACTIVE cũ của các coin đó - vẫn giữ lịch sử.
        Nếu replace=False: bổ sung/cập nhật.
        """
        from analytics.scenario_generator import ScenarioGenerator
        generator = ScenarioGenerator()
        try:
            target_coins = coins or ["BTC", "ETH", "PAXG"]
            new_scenarios = await generator.generate_all(target_coins)
            if not new_scenarios:
                return {}

            # Lấy trạng thái mới nhất trên đĩa trước khi sửa (watcher có thể vừa ghi)
            self._reload_if_changed()

            if replace:
                coins_to_replace = {c.upper() for c in target_coins}
                for sc in self.scenarios.values():
                    if sc.get("status") == "ACTIVE" and sc.get("coin", "").upper() in coins_to_replace:
                        self._close(sc, "REPLACED", "Thay thế bởi kịch bản mới (/scenario gen)")

            expires_at = (datetime.now() + timedelta(hours=Config.SCENARIO_TTL_HOURS)).isoformat()
            for sc in new_scenarios.values():
                sc.setdefault("expires_at", expires_at)

            self.scenarios.update(new_scenarios)
            self._prune_history()
            self.save_scenarios()
            return new_scenarios
        finally:
            await generator.analyzer.close()
