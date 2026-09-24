"""
Real-time Signal Scanner Daemon
Chạy nền liên tục để quét các tín hiệu kỹ thuật từ TechnicalAnalyzer.
Tự động gửi thông báo về Telegram / Zalo khi phát hiện tín hiệu đảo chiều.

Tích hợp AI Intelligence (Phase 1-5):
- ML Signal Booster (confidence scoring)
- Market Regime Detector (trending/ranging/volatile)
- News Intelligence (LLM + event history)
- Whale Tracker (smart money signals)
- Trade Analyzer (post-mortem)
"""
import asyncio
import html
from datetime import datetime
from loguru import logger

from core.config import Config
from analytics.technical import TechnicalAnalyzer
from notifiers.telegram_bot import TelegramNotifier
from notifiers.zalo_bot import ZaloNotifier

# AI Intelligence modules (graceful import)
try:
    from analytics.market_regime import MarketRegimeDetector
except ImportError:
    MarketRegimeDetector = None

try:
    from analytics.whale_tracker import WhaleTracker
except ImportError:
    WhaleTracker = None

try:
    from analytics.news_intelligence import NewsIntelligence
except ImportError:
    NewsIntelligence = None

try:
    from analytics.ml_signal_booster import AdaptiveSignalBooster, get_booster
except ImportError:
    AdaptiveSignalBooster = None
    get_booster = None

try:
    from analytics.trade_analyzer import TradeAnalyzer
except ImportError:
    TradeAnalyzer = None


class SignalScanner:
    """
    Quét tín hiệu kỹ thuật real-time cho các cặp tiền và timeframes.
    Gửi thông báo tức thời khi phát hiện đảo chiều (LONG / SHORT).
    """

    def __init__(self, symbols: list[str] = None, timeframes: list[str] = None, interval_seconds: int = 300, trade_engine = None, signal_tracker = None):
        self.symbols = symbols or ["BTC/USDT", "ETH/USDT", "SOL/USDT", "PAXG/USDT"]
        self.timeframes = timeframes or ["15m", "1h", "4h"]
        self.interval = interval_seconds
        
        self.analyzer = TechnicalAnalyzer()
        self.tg_notifier = TelegramNotifier()
        self.zalo_notifier = ZaloNotifier()
        self.trade_engine = trade_engine
        self.signal_tracker = signal_tracker
        
        # Lưu trữ trạng thái tín hiệu trước đó: key = "SYMBOL_TIMEFRAME", value = "LONG"/"SHORT"/"NEUTRAL"
        self.last_signals: dict[str, str] = {}
        
        self._running = False
        self._task: asyncio.Task | None = None
        self._closed = False  # M7: danh dau da dong tai nguyen mang (idempotent)

        # === AI Intelligence Modules ===
        self.regime_detector = MarketRegimeDetector() if MarketRegimeDetector else None
        self.whale_tracker = WhaleTracker() if (WhaleTracker and Config.WHALE_ENABLED) else None
        self.news_intel = NewsIntelligence() if (NewsIntelligence and Config.NEWS_INTEL_ENABLED) else None
        self.ml_booster = get_booster() if (get_booster and Config.ML_ENABLED) else None
        self.trade_analyzer = TradeAnalyzer() if TradeAnalyzer else None

        # Cache for AI intelligence results (refreshed each scan cycle)
        self._ai_cache: dict = {}

        ai_modules = []
        if self.regime_detector: ai_modules.append("MarketRegime")
        if self.whale_tracker: ai_modules.append("WhaleTracker")
        if self.news_intel: ai_modules.append("NewsIntel")
        if self.ml_booster: ai_modules.append(f"MLBooster(samples={self.ml_booster.get_status()['total_samples']})")
        if self.trade_analyzer: ai_modules.append("TradeAnalyzer")
        logger.info(f"🧠 AI Intelligence modules loaded: {', '.join(ai_modules) if ai_modules else 'None'}")

    def start(self):
        """Khởi chạy task quét tín hiệu chạy nền."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._scan_loop())
            logger.info(f"🚀 SignalScanner đã khởi động (Khoảng thời gian: {self.interval}s, Coins: {self.symbols}, TFs: {self.timeframes})")

    def stop(self):
        """Dừng quét tín hiệu và hẹn đóng tài nguyên mạng."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("⏹️ SignalScanner đã dừng.")
        # Dong tai nguyen mang (ccxt session, aiohttp whale tracker) — idempotent.
        # Neu dang trong event loop thi hen task; main.py se await truc tiep qua aclose().
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.aclose())
        except RuntimeError:
            pass  # Khong co event loop (vd goi tu script sync) — aclose se duoc goi rieng

    async def aclose(self):
        """
        Dong tai nguyen mang cua scanner (TechnicalAnalyzer/ccxt, WhaleTracker/aiohttp).
        Idempotent — goi nhieu lan an toan (stop() hen + main.py await truc tiep).
        """
        if self._closed:
            return
        self._closed = True
        if self.analyzer:
            try:
                await self.analyzer.close()
            except Exception as e:
                logger.debug(f"Loi dong TechnicalAnalyzer: {e}")
        if self.whale_tracker:
            try:
                await self.whale_tracker.close()
            except Exception as e:
                logger.debug(f"Loi dong WhaleTracker: {e}")
        logger.info("🧹 SignalScanner đã đóng tài nguyên mạng.")

    def calculate_signal_rating(self, signal: dict, tf: str, macro_trend: str) -> int:
        """
        Tính số sao (rating) cho tín hiệu: từ 1 đến 5 sao.
        """
        direction = signal.get("direction", "NEUTRAL")
        if direction == "NEUTRAL":
            return 0
            
        rating = 3  # Điểm cơ sở (Mặc định 3 sao cho tín hiệu đủ điều kiện)
        
        bull_score = signal.get("bull_score", 0)
        bear_score = signal.get("bear_score", 0)
        indicator_score = bull_score if direction == "LONG" else bear_score
        
        # 1. Chỉ báo kỹ thuật đồng thuận mạnh
        if indicator_score >= 5:
            rating += 1
            
        # 2. Đồng thuận xu hướng lớn 4h
        if tf in ("15m", "1h"):
            is_trend_aligned = (direction == "LONG" and macro_trend == "BULLISH") or (direction == "SHORT" and macro_trend == "BEARISH")
            if is_trend_aligned:
                rating += 1
        elif tf == "4h":
            rating += 1
            
        # 3. ADX Trend Filter cho Swing (1h, 4h): nếu không có lực đẩy ADX mạnh (ADX < 25), giảm 1 sao tránh sideway
        reasons = signal.get("reasons", [])
        reasons_str = "".join(reasons)
        has_adx = "ADX manh" in reasons_str
        if tf in ("1h", "4h") and not has_adx:
            rating -= 1

        # 4. Nếu có cảnh báo ngược xu hướng EMA50/EMA200, ghi đè rating thấp
        has_warning = "Canh bao" in reasons_str or "Huy" in reasons_str
        if has_warning:
            is_trend_opposite = False
            if tf in ("15m", "1h") and macro_trend != "NEUTRAL":
                is_trend_opposite = (direction == "LONG" and macro_trend == "BEARISH") or (direction == "SHORT" and macro_trend == "BULLISH")
            rating = 1 if is_trend_opposite else 2
        
        return min(max(rating, 1), 5)

    async def _refresh_ai_intelligence(self):
        """
        Refresh AI intelligence data moi scan cycle.
        Chay song song: Whale data per symbol, sau do fetch News.
        """
        tasks = {}

        # Whale tracker — per-symbol
        if self.whale_tracker:
            for sym in self.symbols:
                binance_sym = sym.replace("/", "").replace("USDT", "") + "USDT"
                tasks[f"whale_{binance_sym}"] = self.whale_tracker.compute_whale_bias(binance_sym)

        # Run whale tasks in parallel (nếu có)
        if tasks:
            keys = list(tasks.keys())
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(keys, results):
                if isinstance(result, Exception):
                    logger.warning(f"[AI] {key} error: {result}")
                else:
                    self._ai_cache[key] = result

        # News intelligence (chạy sau whale, dùng chung cho mọi symbol)
        if self.news_intel:
            try:
                from analytics.macro_calendar import MacroCalendar
                macro = MacroCalendar()
                try:
                    events = await macro.get_all_events(7)
                finally:
                    await macro.close()

                # M2 fix: lay tin tuc that (truoc day hardcode recent_news=[] -> luon NEUTRAL)
                recent_news = await self._fetch_recent_news()

                news_bias = await self.news_intel.get_news_bias(
                    recent_news=recent_news, upcoming_events=events
                )
                self._ai_cache["news"] = news_bias

                # C4 fix: tu dong ghi nhan ket qua cac su kien macro da qua vao Event Impact DB
                try:
                    recorded = await self.news_intel.auto_record_past_events(events)
                    if recorded:
                        logger.info(f"📚 [NewsIntel] Da ghi nhan {recorded} su kien vao Event Impact DB")
                except Exception as rec_err:
                    logger.debug(f"[AI] Record event outcomes error: {rec_err}")
            except Exception as e:
                logger.debug(f"[AI] News intel error: {e}")

        # Log AI summary
        news = self._ai_cache.get("news", {})
        parts = []
        # Log whale cho BTC (primary)
        btc_whale = self._ai_cache.get("whale_BTCUSDT", {})
        if btc_whale.get("whale_bias", "NEUTRAL") != "NEUTRAL":
            parts.append(f"🐋 BTC Whale={btc_whale['whale_bias']}(adj={btc_whale.get('rating_adjust', 0):+d})")
        if news.get("news_bias", "NEUTRAL") != "NEUTRAL":
            parts.append(f"📰 News={news['news_bias']}(adj={news.get('rating_adjust', 0):+d})")
        if news.get("warnings"):
            parts.append(f"⚠️ {len(news['warnings'])} warnings")
        if parts:
            logger.info(f"🧠 [AI Intelligence] {' | '.join(parts)}")

    async def _fetch_recent_news(self) -> list:
        """
        Lay tin tuc that + cham sentiment (CryptoPanic/RSS + keyword sentiment).

        Truoc day scanner hardcode recent_news=[] o call-site nen nhanh news sentiment
        luon tra ve 0 -> news bias luon NEUTRAL (M2 fix).
        Neu Config.NEWS_LLM_FOR_HIGH_IMPACT=true thi bo sung them phan tich LLM
        cho toi da 2 tin quan trong (co cache de tiet kiem credit).
        """
        try:
            from data_ingestion.news_crawler import NewsCrawler
            from analytics.sentiment import SentimentAnalyzer
        except ImportError:
            return []

        crawler = NewsCrawler()
        try:
            raw_news = await crawler.fetch_all(limit=10)
        except Exception as e:
            logger.debug(f"[AI] News fetch error: {e}")
            return []
        finally:
            try:
                await crawler.close()
            except Exception:
                pass

        if not raw_news:
            return []

        try:
            analyzed = SentimentAnalyzer().analyze_news_batch(raw_news)
        except Exception as e:
            logger.debug(f"[AI] Sentiment batch error: {e}")
            return []

        if Config.NEWS_LLM_FOR_HIGH_IMPACT and self.news_intel:
            try:
                analyzed = await self.news_intel.enrich_news_with_llm(analyzed, max_items=2)
            except Exception as e:
                logger.debug(f"[AI] News LLM enrich error: {e}")

        return analyzed

    def _apply_ai_adjustments(self, base_rating: int, signal: dict, df, tf: str, macro_trend: str, symbol: str = "") -> tuple:
        """
        Apply tat ca AI module adjustments len base_rating.
        Returns (adjusted_rating, ai_details_dict).
        """
        ai_details = {}
        total_adjust = 0
        signal_dir = signal.get("direction", "NEUTRAL")

        # 1. Market Regime (H2 fix: direction-aware)
        if self.regime_detector and df is not None and not df.empty:
            try:
                regime_result = self.regime_detector.detect(df)
                raw_adj = regime_result.get("adjustments", {}).get("rating_adjust", 0)
                trend_dir = regime_result.get("trend_direction", "NEUTRAL")

                # Direction-aware: chi boost neu signal cung huong voi trend
                if raw_adj > 0 and trend_dir != "NEUTRAL":
                    if (signal_dir == "LONG" and trend_dir == "BULLISH") or \
                       (signal_dir == "SHORT" and trend_dir == "BEARISH"):
                        regime_adj = raw_adj       # Cung huong → boost
                    elif (signal_dir == "LONG" and trend_dir == "BEARISH") or \
                         (signal_dir == "SHORT" and trend_dir == "BULLISH"):
                        regime_adj = -raw_adj      # Nguoc huong → penalize
                    else:
                        regime_adj = 0
                else:
                    regime_adj = raw_adj  # Ranging/Volatile penalty giu nguyen

                total_adjust += regime_adj
                ai_details["regime"] = {
                    "regime": regime_result["regime"],
                    "confidence": regime_result["confidence"],
                    "trend": trend_dir,
                    "rating_adj": regime_adj,
                }
            except Exception as e:
                logger.debug(f"[AI] Regime error: {e}")

        # 2. Whale bias (H1 fix: per-symbol lookup)
        binance_sym = symbol.replace("/", "").replace("USDT", "") + "USDT" if symbol else "BTCUSDT"
        whale = self._ai_cache.get(f"whale_{binance_sym}", self._ai_cache.get("whale_BTCUSDT", {}))
        if whale.get("whale_bias", "NEUTRAL") != "NEUTRAL":
            whale_dir = whale["whale_bias"]
            whale_adj = whale.get("rating_adjust", 0)

            # Whale bias dong thuan voi signal → boost; nguoc lai → reduce
            if (signal_dir == "LONG" and whale_dir == "BULLISH") or \
               (signal_dir == "SHORT" and whale_dir == "BEARISH"):
                total_adjust += abs(whale_adj)  # Dong thuan = +
            elif (signal_dir == "LONG" and whale_dir == "BEARISH") or \
                 (signal_dir == "SHORT" and whale_dir == "BULLISH"):
                total_adjust -= abs(whale_adj)  # Nguoc chieu = -

            ai_details["whale"] = {
                "bias": whale_dir,
                "confidence": whale.get("whale_confidence", 0),
                "rating_adj": whale_adj,
                "signals_count": len(whale.get("signals", [])),
                "symbol": binance_sym,
            }

        # 3. News bias (H2 fix: direction-aware)
        news = self._ai_cache.get("news", {})
        if news:
            raw_news_adj = news.get("rating_adjust", 0)
            news_bias = news.get("news_bias", "NEUTRAL")

            # Direction-aware: chi boost neu signal cung huong voi news
            if raw_news_adj != 0 and news_bias != "NEUTRAL":
                if (signal_dir == "LONG" and news_bias == "BULLISH") or \
                   (signal_dir == "SHORT" and news_bias == "BEARISH"):
                    news_adj = raw_news_adj       # Cung huong
                elif (signal_dir == "LONG" and news_bias == "BEARISH") or \
                     (signal_dir == "SHORT" and news_bias == "BULLISH"):
                    news_adj = -abs(raw_news_adj)  # Nguoc huong → penalize
                else:
                    news_adj = 0
            else:
                news_adj = raw_news_adj  # Neutral hoac no-adj

            total_adjust += news_adj
            ai_details["news"] = {
                "bias": news_bias,
                "rating_adj": news_adj,
                "should_pause": news.get("should_pause_auto_trade", False),
                "warnings": news.get("warnings", []),
            }

        # 4. ML confidence
        if self.ml_booster and df is not None:
            try:
                regime = ai_details.get("regime", {}).get("regime", "RANGING")
                macro_risk = "NORMAL"  # Will be updated from cached macro data
                ml_result = self.ml_booster.predict(df, signal, regime, macro_risk, tf)
                ml_adj = ml_result.get("rating_adjust", 0)
                total_adjust += ml_adj
                ai_details["ml"] = {
                    "confidence": ml_result["confidence"],
                    "rating_adj": ml_adj,
                    "is_trained": ml_result["is_trained"],
                    "accuracy": ml_result.get("model_accuracy", 0),
                    # PHAI giu '_features' de trade_engine thu thap sample khi dong lenh.
                    # Neu thieu key nay thi feedback loop ML bi dut (model khong bao gio train).
                    "_features": ml_result.get("_features"),
                }
            except Exception as e:
                logger.debug(f"[AI] ML error: {e}")

        # Clamp total adjustment
        total_adjust = max(-3, min(3, total_adjust))
        adjusted_rating = max(1, min(5, base_rating + total_adjust))

        ai_details["total_adjust"] = total_adjust
        ai_details["base_rating"] = base_rating
        ai_details["final_rating"] = adjusted_rating

        return adjusted_rating, ai_details

    async def _scan_loop(self):
        # Chờ 15 giây đầu tiên để các service khác ổn định trước khi quét lần đầu
        await asyncio.sleep(15)
        
        while self._running:
            try:
                logger.info("🔍 Đang chạy chu kỳ quét tín hiệu kỹ thuật real-time (Song song)...")

                # === Refresh AI Intelligence trước khi quét ===
                try:
                    await self._refresh_ai_intelligence()
                except Exception as ai_err:
                    logger.warning(f"[AI] Refresh error (non-fatal): {ai_err}")
                
                # Tạo danh sách các task cần chạy song song
                tasks = []
                keys = []
                for symbol in self.symbols:
                    for tf in self.timeframes:
                        keys.append((symbol, tf))
                        tasks.append(self.analyzer.analyze_full(symbol, tf))
                
                # Chạy song song toàn bộ các truy vấn phân tích
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Gom kết quả phân tích theo cặp coin để lọc đa khung thời gian
                all_analyses = {}
                dfs_by_key = {}
                for (symbol, tf), res in zip(keys, results):
                    if isinstance(res, Exception) or not res:
                        if isinstance(res, Exception):
                            logger.error(f"Lỗi phân tích song song {symbol}_{tf}: {res}")
                        continue
                    df, signal = res
                    all_analyses[(symbol, tf)] = (df, signal)
                    # Vẫn lưu df vào dfs_by_key cho tất cả để phục vụ tính Smart Levels nếu cần
                    dfs_by_key[f"{symbol}_{tf}"] = df

                # Xử lý tín hiệu đã được lọc đồng thuận xu hướng
                for symbol in self.symbols:
                    # 1. Xác định xu hướng lớn từ khung 4h (khung lớn nhất được quét)
                    macro_trend = "NEUTRAL"
                    res_4h = all_analyses.get((symbol, "4h"))
                    if res_4h:
                        df_4h, signal_4h = res_4h
                        if df_4h is not None and not df_4h.empty:
                            import pandas as pd
                            latest_4h = df_4h.iloc[-1]
                            price_4h = float(latest_4h["close"])
                            ema50_4h = latest_4h.get("ema50")
                            
                            if ema50_4h is not None and not pd.isna(ema50_4h):
                                if price_4h > ema50_4h:
                                    macro_trend = "BULLISH"
                                elif price_4h < ema50_4h:
                                    macro_trend = "BEARISH"
                                logger.info(f"📈 [Macro Trend Filter] {symbol} 4h Price (${price_4h:.2f}) vs EMA50 (${ema50_4h:.2f}) -> {macro_trend}")
                            
                            # Fallback sang signal 4h nếu EMA50 chưa có
                            if macro_trend == "NEUTRAL" and signal_4h:
                                dir_4h = signal_4h.get("direction", "NEUTRAL")
                                if dir_4h == "LONG":
                                    macro_trend = "BULLISH"
                                elif dir_4h == "SHORT":
                                    macro_trend = "BEARISH"

                    # 2. Xử lý từng khung thời gian
                    for tf in self.timeframes:
                        res_tf = all_analyses.get((symbol, tf))
                        if not res_tf:
                            continue
                        df, signal = res_tf
                        if not signal or signal.get("direction") == "NEUTRAL":
                            continue
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
                            is_first_scan = (last_dir is None)
                            
                            # Nếu là lần quét đầu tiên cho cặp này/khung này, ghi nhận trạng thái nền
                            if is_first_scan:
                                self.last_signals[key] = direction
                                logger.debug(f"Khởi tạo trạng thái ban đầu cho {key}: {direction}")
                                if direction == "NEUTRAL":
                                    continue
                            elif direction == last_dir:
                                continue
                            else:
                                logger.warning(f"🚨 Phát hiện đảo chiều tín hiệu trên {key}: {last_dir} -> {direction}")
                                self.last_signals[key] = direction
                                
                            # Chỉ xử lý khi có tín hiệu cụ thể LONG hoặc SHORT
                            if direction in ("LONG", "SHORT"):
                                coin_name = symbol.split("/")[0].upper()
                                if coin_name not in ("BTC", "ETH"):
                                    logger.info(f"⏭️ [Scanner] Bỏ qua thông báo và giao dịch Futures cho {coin_name} (chỉ chấp nhận BTC/ETH)")
                                    continue
                                    reasons = signal.get("reasons", [])
                                    reasons_str = ", ".join(reasons) if reasons else "Chỉ báo kỹ thuật đảo chiều"
                                    
                                    entry = signal.get("entry", signal.get("price", 0))
                                    sl = signal.get("sl", 0)
                                    tp = signal.get("tp", 0)
                                    
                                    # Mặc định dùng static levels
                                    smart_sl = sl
                                    smart_tp1 = entry * (1.015 if direction == "LONG" else 0.985)
                                    smart_tp2 = entry * (1.030 if direction == "LONG" else 0.970)
                                    smart_tp3 = tp
                                    
                                    # Thử tính Smart Levels từ DataFrame
                                    smart_levels = None
                                    df = dfs_by_key.get(key)
                                    if df is not None:
                                        try:
                                            from analytics.macro_calendar import MacroCalendar
                                            macro = MacroCalendar()
                                            risk_data = await macro.assess_risk()
                                            macro_risk = risk_data.get("risk_level", "NORMAL")
                                            await macro.close()
                                            
                                            smart_levels = self.analyzer.compute_smart_levels(
                                                df=df,
                                                direction=direction,
                                                leverage=10,
                                                macro_risk=macro_risk
                                            )
                                            if "error" not in smart_levels:
                                                smart_sl = smart_levels["sl"]
                                                smart_tp1 = smart_levels["tp1"]
                                                smart_tp2 = smart_levels["tp2"]
                                                smart_tp3 = smart_levels["tp3"]
                                                logger.info(f"✨ [Smart Levels] Da tinh muc SL/TP cho {key}: SL={smart_sl}, TP1={smart_tp1}, TP2={smart_tp2}, TP3={smart_tp3}")
                                        except Exception as ex:
                                            logger.error(f"Loi tinh toan Smart Levels cho {key}: {ex}")

                                    # Tính rating cơ sở
                                    base_rating = self.calculate_signal_rating(signal, tf, macro_trend)
                                    
                                    # === AI INTELLIGENCE ADJUSTMENTS ===
                                    rating, ai_details = self._apply_ai_adjustments(
                                        base_rating, signal, df, tf, macro_trend, symbol=symbol
                                    )
                                    signal["rating"] = rating
                                    signal["ai_details"] = ai_details
                                    
                                    # Log AI adjustment nếu có thay đổi
                                    if ai_details.get("total_adjust", 0) != 0:
                                        logger.info(
                                            f"🧠 [AI] {key}: Base={base_rating}⭐ → Final={rating}⭐ "
                                            f"(adjust={ai_details['total_adjust']:+d}) | "
                                            f"Regime={ai_details.get('regime', {}).get('regime', '?')} "
                                            f"Whale={ai_details.get('whale', {}).get('bias', '?')} "
                                            f"News={ai_details.get('news', {}).get('bias', '?')} "
                                            f"ML={ai_details.get('ml', {}).get('confidence', '?')}"
                                        )

                                    # Check news: should_pause_auto_trade?
                                    news_pause = ai_details.get("news", {}).get("should_pause", False)
                                    
                                    # Tự động vào lệnh nếu Auto Trade bật và tín hiệu >= 4 sao
                                    if self.trade_engine and self.trade_engine.auto_trade_enabled and self.signal_tracker:
                                        if news_pause:
                                            logger.warning(f"⚠️ [AI] Auto-trade tạm dừng do sự kiện macro quan trọng")
                                        elif rating >= 4:
                                            signal_key = f"{coin_name}_{tf}"
                                            if signal_key not in self.trade_engine.positions:
                                                logger.info(f"🤖 [Auto Trade] Tự động mở vị thế cho {signal_key} (Rating: {rating} sao, AI-adjusted)")
                                                # Đòn bẩy thích ứng từ Smart SL/TP (cực đại là 10x)
                                                rec_lev = smart_levels.get("recommended_leverage", 10) if (smart_levels and "error" not in smart_levels) else 10
                                                trade_leverage = min(rec_lev, 10)
                                                trade_leverage = max(trade_leverage, 1)
                                                
                                                # AI adjustments cho leverage và SL
                                                regime_adj = ai_details.get("regime", {}).get("regime", "")
                                                news_adj = self._ai_cache.get("news", {})
                                                if regime_adj == "VOLATILE":
                                                    trade_leverage = max(1, trade_leverage // 2)
                                                if news_adj.get("leverage_mult", 1.0) < 1.0:
                                                    trade_leverage = max(1, int(trade_leverage * news_adj["leverage_mult"]))
                                                
                                                self.signal_tracker.add_signal({
                                                    "key": signal_key,
                                                    "coin": coin_name,
                                                    "type": "FUTURES",
                                                    "direction": direction,
                                                    "entry": entry,
                                                    "sl": smart_sl,
                                                    "tp1": round(smart_tp1, 2),
                                                    "tp2": round(smart_tp2, 2),
                                                    "tp3": round(smart_tp3, 2),
                                                    "chat_id": self.tg_notifier.chat_id,
                                                    "leverage": trade_leverage,
                                                    "rating": rating,
                                                    "tf": tf,
                                                    "atr": smart_levels.get("atr", 0) if (smart_levels and "error" not in smart_levels) else 0,
                                                    "ai_details": ai_details,
                                                })
                                        else:
                                            logger.info(f"⏭️ [Auto Trade] Bỏ qua {coin_name}_{tf} vì rating={rating} < 4 sao")
                                    
# M7 fix: CRITICAL event khong con tru rating nua (chi pause auto-trade)
                                    # → canh bao AI/su kien phai di kem tin nhan de trader manual biet rui ro.
                                    ai_notes = ""
                                    warn_parts = list(ai_details.get("news", {}).get("warnings", []))
                                    warn_parts += list(ai_details.get("whale", {}).get("warnings", []))
                                    if news_pause:
                                        warn_parts.append("⛔ Auto-trade tam dung (su kien macro CRITICAL)")
                                    if warn_parts:
                                        ai_notes = " | ⚠️ " + " | ".join(str(w) for w in warn_parts[:2])

                                    # Gửi thông báo khi có đảo chiều hoặc tín hiệu khởi đầu mạnh (>= 4 sao)
                                    should_notify = (not is_first_scan) or (is_first_scan and rating >= 4)
                                    if should_notify:
                                        # 1. Gửi Telegram Notifier
                                        logger.info(f"📨 Đang gửi tín hiệu Telegram cho {key}...")
                                        await self.tg_notifier.send_signal(
                                            coin=f"{coin_name} ({tf})",
                                            direction=direction,
                                            entry=entry,
                                            sl=smart_sl,
                                            tp=smart_tp3,
                                            reason=html.escape(reasons_str + ai_notes),
                                            rating=rating
                                        )
                                        
                                        # 2. Gửi Zalo Notifier (nếu có cấu hình)
                                        zalo_text = (
                                            f"🚨 PHÁT HIỆN TÍN HIỆU ({tf.upper()})\n"
                                            f"━━━━━━━━━━━━━━━━━━\n"
                                            f"🪙 Coin: {coin_name}\n"
                                            f"👉 Hướng: {direction}\n"
                                            f"⭐ Độ tin cậy: {'⭐' * rating}\n"
                                            f"📍 Entry: ${entry:,.4f}\n"
                                            f"🛑 Stop Loss: ${smart_sl:,.4f}\n"
                                            f"🎯 Take Profit: ${smart_tp3:,.4f}\n"
                                            f"💡 Lý do: {reasons_str}{ai_notes}\n"
                                            f"━━━━━━━━━━━━━━━━━━"
                                        )
                                        await self.zalo_notifier.send_message(zalo_text)
                                    
                        except Exception as inner_e:
                            logger.error(f"Lỗi xử lý kết quả {key}: {inner_e}")
                            
            except Exception as e:
                logger.error(f"Lỗi trong vòng lặp chính SignalScanner: {e}")
                
            # Chờ đợi cho chu kỳ quét tiếp theo
            await asyncio.sleep(self.interval)
