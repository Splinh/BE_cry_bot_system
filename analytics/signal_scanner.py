"""
Real-time Signal Scanner Daemon
Chạy nền liên tục để quét các tín hiệu kỹ thuật từ TechnicalAnalyzer.
Tự động gửi thông báo về Telegram / Zalo khi phát hiện tín hiệu đảo chiều.
"""
import asyncio
import html
from datetime import datetime
from loguru import logger

from analytics.technical import TechnicalAnalyzer
from notifiers.telegram_bot import TelegramNotifier
from notifiers.zalo_bot import ZaloNotifier


class SignalScanner:
    """
    Quét tín hiệu kỹ thuật real-time cho các cặp tiền và timeframes.
    Gửi thông báo tức thời khi phát hiện đảo chiều (LONG / SHORT).
    """

    def __init__(self, symbols: list[str] = None, timeframes: list[str] = None, interval_seconds: int = 300):
        self.symbols = symbols or ["BTC/USDT", "ETH/USDT", "SOL/USDT", "PAXG/USDT"]
        self.timeframes = timeframes or ["15m", "1h", "4h"]
        self.interval = interval_seconds
        
        self.analyzer = TechnicalAnalyzer()
        self.tg_notifier = TelegramNotifier()
        self.zalo_notifier = ZaloNotifier()
        
        # Lưu trữ trạng thái tín hiệu trước đó: key = "SYMBOL_TIMEFRAME", value = "LONG"/"SHORT"/"NEUTRAL"
        self.last_signals: dict[str, str] = {}
        
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self):
        """Khởi chạy task quét tín hiệu chạy nền."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._scan_loop())
            logger.info(f"🚀 SignalScanner đã khởi động (Khoảng thời gian: {self.interval}s, Coins: {self.symbols}, TFs: {self.timeframes})")

    def stop(self):
        """Dừng quét tín hiệu."""
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("⏹️ SignalScanner đã dừng.")

    async def _scan_loop(self):
        # Chờ 15 giây đầu tiên để các service khác ổn định trước khi quét lần đầu
        await asyncio.sleep(15)
        
        while self._running:
            try:
                logger.info("🔍 Đang chạy chu kỳ quét tín hiệu kỹ thuật real-time (Song song)...")
                
                # Tạo danh sách các task cần chạy song song
                tasks = []
                keys = []
                for symbol in self.symbols:
                    for tf in self.timeframes:
                        keys.append((symbol, tf))
                        tasks.append(self.analyzer.analyze(symbol, tf))
                
                # Chạy song song toàn bộ các truy vấn phân tích
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Gom kết quả phân tích theo cặp coin để lọc đa khung thời gian
                signals_by_symbol = {}
                for (symbol, tf), signal in zip(keys, results):
                    if isinstance(signal, Exception) or not signal:
                        if isinstance(signal, Exception):
                            logger.error(f"Lỗi phân tích song song {symbol}_{tf}: {signal}")
                        continue
                    if symbol not in signals_by_symbol:
                        signals_by_symbol[symbol] = {}
                    signals_by_symbol[symbol][tf] = signal

                # Xử lý tín hiệu đã được lọc đồng thuận xu hướng
                for symbol, tf_signals in signals_by_symbol.items():
                    # 1. Xác định xu hướng lớn từ khung 4h (khung lớn nhất được quét)
                    signal_4h = tf_signals.get("4h")
                    macro_trend = "NEUTRAL"
                    if signal_4h:
                        reasons_4h = signal_4h.get("reasons", [])
                        dir_4h = signal_4h.get("direction", "NEUTRAL")
                        reasons_4h_str = "".join(reasons_4h)
                        
                        if dir_4h == "LONG":
                            macro_trend = "BULLISH"
                        elif dir_4h == "SHORT":
                            macro_trend = "BEARISH"
                        elif "Gia tren EMA20, EMA50" in reasons_4h_str or "Gia tren EMA50" in reasons_4h_str:
                            macro_trend = "BULLISH"
                        elif "Gia duoi EMA20, EMA50" in reasons_4h_str or "Gia duoi EMA50" in reasons_4h_str:
                            macro_trend = "BEARISH"
                        elif "Huy LONG: Gia duoi EMA50" in reasons_4h_str:
                            macro_trend = "BEARISH"
                        elif "Huy SHORT: Gia tren EMA50" in reasons_4h_str:
                            macro_trend = "BULLISH"

                    # 2. Xử lý từng khung thời gian
                    for tf, signal in tf_signals.items():
                        key = f"{symbol}_{tf}"
                        try:
                            direction = signal.get("direction", "NEUTRAL")
                            
                            # Chỉ áp dụng lọc đồng thuận đa khung thời gian cho các khung nhỏ (15m, 1h)
                            if tf in ("15m", "1h") and macro_trend != "NEUTRAL":
                                if direction == "LONG" and macro_trend == "BEARISH":
                                    logger.warning(f"🚫 Lọc đồng thuận: Bỏ qua tín hiệu LONG trên {key} do xu hướng lớn 4h là BEARISH")
                                    direction = "NEUTRAL"
                                    signal["direction"] = "NEUTRAL"
                                elif direction == "SHORT" and macro_trend == "BULLISH":
                                    logger.warning(f"🚫 Lọc đồng thuận: Bỏ qua tín hiệu SHORT trên {key} do xu hướng lớn 4h là BULLISH")
                                    direction = "NEUTRAL"
                                    signal["direction"] = "NEUTRAL"

                            last_dir = self.last_signals.get(key)
                            
                            # Nếu là lần quét đầu tiên cho cặp này/khung này, ghi nhận trạng thái nền
                            if last_dir is None:
                                self.last_signals[key] = direction
                                logger.debug(f"Khởi tạo trạng thái ban đầu cho {key}: {direction}")
                                continue
                            
                            # Phát hiện sự thay đổi tín hiệu (đảo chiều)
                            if direction != last_dir:
                                logger.warning(f"🚨 Phát hiện đảo chiều tín hiệu trên {key}: {last_dir} -> {direction}")
                                self.last_signals[key] = direction
                                
                                # Chỉ gửi thông báo khi có tín hiệu cụ thể LONG hoặc SHORT
                                if direction in ("LONG", "SHORT"):
                                    coin_name = symbol.split("/")[0]
                                    reasons = signal.get("reasons", [])
                                    reasons_str = ", ".join(reasons) if reasons else "Chỉ báo kỹ thuật đảo chiều"
                                    
                                    entry = signal.get("entry", signal.get("price", 0))
                                    sl = signal.get("sl", 0)
                                    tp = signal.get("tp", 0)
                                    
                                    # 1. Gửi Telegram Notifier
                                    logger.info(f"📨 Đang gửi tín hiệu Telegram cho {key}...")
                                    await self.tg_notifier.send_signal(
                                        coin=f"{coin_name} ({tf})",
                                        direction=direction,
                                        entry=entry,
                                        sl=sl,
                                        tp=tp,
                                        reason=html.escape(reasons_str)
                                    )
                                    
                                    # 2. Gửi Zalo Notifier (nếu có cấu hình)
                                    zalo_text = (
                                        f"🚨 PHÁT HIỆN TÍN HIỆU ĐẢO CHIỀU ({tf.upper()})\n"
                                        f"━━━━━━━━━━━━━━━━━━\n"
                                        f"🪙 Coin: {coin_name}\n"
                                        f"👉 Hướng: {direction}\n"
                                        f"📍 Entry: ${entry:,.4f}\n"
                                        f"🛑 Stop Loss: ${sl:,.4f}\n"
                                        f"🎯 Take Profit: ${tp:,.4f}\n"
                                        f"💡 Lý do: {reasons_str}\n"
                                        f"━━━━━━━━━━━━━━━━━━"
                                    )
                                    await self.zalo_notifier.send_message(zalo_text)
                                    
                        except Exception as inner_e:
                            logger.error(f"Lỗi xử lý kết quả {key}: {inner_e}")
                            
            except Exception as e:
                logger.error(f"Lỗi trong vòng lặp chính SignalScanner: {e}")
                
            # Chờ đợi cho chu kỳ quét tiếp theo
            await asyncio.sleep(self.interval)
