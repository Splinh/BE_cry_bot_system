"""
Adaptive Signal Booster — ML-based signal confidence scoring.

Dùng LightGBM classifier train trên lịch sử trade để:
- Dự đoán xác suất trade sẽ thắng (confidence_score 0-1)
- Xác định chỉ báo nào hiệu quả nhất (feature importance)
- Tự động retrain khi có đủ data mới

Minimum: 30 trades lịch sử để bắt đầu train. Trước đó → passthrough.
"""
import json
import os
import pickle
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


# File paths
ML_MODEL_FILE = "data/ml_signal_model.pkl"
ML_TRAINING_FILE = "data/ml_training_data.json"

# Lock bao ve viec ghi file trong cung process
# (tranh 2 worker thread cung ghi file .tmp -> file hong)
_SAVE_LOCK = threading.Lock()

# Feature names — thu tu phai co dinh
FEATURE_NAMES = [
    "rsi", "macd_hist", "ema20_dist", "ema50_dist",
    "bb_pctb", "vwap_dist", "adx", "atr_ratio",
    "vol_ratio", "fib_proximity", "regime_trending",
    "regime_ranging", "regime_volatile", "macro_risk_score",
    "tf_15m", "tf_1h", "tf_4h",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "bull_score", "bear_score",
]


class AdaptiveSignalBooster:
    """
    ML-based confidence scoring cho signals.
    Train tren lich su trade de du doan xac suat thang.
    """

    MIN_SAMPLES = 30          # So trade toi thieu de bat dau train
    RETRAIN_THRESHOLD = 20    # Train lai sau moi 20 trades moi
    CONFIDENCE_THRESHOLDS = {
        "boost_2": 0.80,      # +2 sao
        "boost_1": 0.65,      # +1 sao
        "neutral_low": 0.35,  # Duoi muc nay: -1 sao
    }

    def __init__(self):
        self.model = None
        self.is_trained = False
        self.training_data: list = []
        self.last_train_count = 0
        self.feature_importance: dict = {}
        self.model_accuracy = 0.0
        # M4 fix: doc tu Config neu co, fallback ve class constant
        try:
            from core.config import Config
            self.MIN_SAMPLES = Config.ML_MIN_TRADES
            self.RETRAIN_THRESHOLD = Config.ML_RETRAIN_INTERVAL
        except Exception:
            pass
        self._load_training_data()
        self._load_model()
        self._loaded_mtime = 0.0
        self._record_mtime()          # Theo doi mtime de phat hien model/data moi tu process khac

    def _load_training_data(self):
        """Doc training data tu file."""
        if os.path.exists(ML_TRAINING_FILE):
            try:
                with open(ML_TRAINING_FILE, "r") as f:
                    self.training_data = json.load(f)
                logger.info(f"[ML] Loaded {len(self.training_data)} training samples")
            except Exception as e:
                logger.error(f"[ML] Loi doc training data: {e}")
                self.training_data = []

    def _save_training_data(self):
        """Luu training data (atomic write de tranh mat du lieu)."""
        os.makedirs(os.path.dirname(ML_TRAINING_FILE), exist_ok=True)
        tmp_file = ML_TRAINING_FILE + ".tmp"
        with _SAVE_LOCK:
            try:
                with open(tmp_file, "w") as f:
                    json.dump(self.training_data, f)
                os.replace(tmp_file, ML_TRAINING_FILE)  # Atomic on same filesystem
                self._record_mtime()
            except Exception as e:
                logger.error(f"[ML] Loi ghi training data: {e}")
                # Cleanup tmp if failed
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def _load_model(self):
        """Load model da train (neu co)."""
        if os.path.exists(ML_MODEL_FILE):
            try:
                with open(ML_MODEL_FILE, "rb") as f:
                    saved = pickle.load(f)
                    self.model = saved.get("model")
                    self.is_trained = True
                    self.model_accuracy = saved.get("accuracy", 0)
                    self.feature_importance = saved.get("feature_importance", {})
                    self.last_train_count = saved.get("train_count", 0)
                logger.info(
                    f"[ML] Model loaded (accuracy={self.model_accuracy:.1%}, "
                    f"train_count={self.last_train_count})"
                )
            except Exception as e:
                logger.error(f"[ML] Loi load model: {e}")
                self.model = None
                self.is_trained = False

    def _save_model(self):
        """Luu model da train (atomic write)."""
        os.makedirs(os.path.dirname(ML_MODEL_FILE), exist_ok=True)
        tmp_file = ML_MODEL_FILE + ".tmp"
        with _SAVE_LOCK:
            try:
                with open(tmp_file, "wb") as f:
                    pickle.dump({
                        "model": self.model,
                        "accuracy": self.model_accuracy,
                        "feature_importance": self.feature_importance,
                        "train_count": len(self.training_data),
                        "trained_at": datetime.now().isoformat(),
                    }, f)
                os.replace(tmp_file, ML_MODEL_FILE)  # Atomic on same filesystem
                self._record_mtime()
            except Exception as e:
                logger.error(f"[ML] Loi luu model: {e}")
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def _record_mtime(self):
        """Ghi nho mtime hien tai cua file data + model."""
        try:
            self._loaded_mtime = max(
                os.path.getmtime(ML_TRAINING_FILE) if os.path.exists(ML_TRAINING_FILE) else 0,
                os.path.getmtime(ML_MODEL_FILE) if os.path.exists(ML_MODEL_FILE) else 0,
            )
        except OSError:
            pass

    def _maybe_reload_from_disk(self):
        """
        Neu file data/model bi thay doi boi process khac (vd bot restart / retrain qua API),
        nap lai de instance nay khong bi 'stale'.
        Chi ton 1 lenh stat() nen goi truoc moi predict la an toan.
        """
        try:
            current = max(
                os.path.getmtime(ML_TRAINING_FILE) if os.path.exists(ML_TRAINING_FILE) else 0,
                os.path.getmtime(ML_MODEL_FILE) if os.path.exists(ML_MODEL_FILE) else 0,
            )
        except OSError:
            return
        if current > self._loaded_mtime:
            logger.info("[ML] Phat hien du lieu/model moi tren dia -> reload")
            self._load_training_data()
            self._load_model()
            self._record_mtime()

    # ==========================================
    #  FEATURE EXTRACTION
    # ==========================================

    def extract_features(
        self,
        df: pd.DataFrame,
        signal: dict,
        regime: str = "RANGING",
        macro_risk: str = "NORMAL",
        timeframe: str = "1h",
    ) -> Optional[np.ndarray]:
        """
        Extract feature vector tu DataFrame + signal data.
        Tra ve numpy array shape (23,) hoac None neu loi.
        """
        if df is None or df.empty or len(df) < 20:
            return None

        try:
            latest = df.iloc[-1]
            price = float(latest["close"])
            if price <= 0:
                return None

            # --- Technical Indicators ---
            rsi = self._safe(latest.get("rsi"), 50) / 100  # Normalize 0-1
            
            macd_hist = self._safe(latest.get("macd_hist"), 0)
            macd_hist_norm = np.tanh(macd_hist / price * 100)  # Normalize

            ema20 = self._safe(latest.get("ema20"), price)
            ema50 = self._safe(latest.get("ema50"), price)
            ema20_dist = (price - ema20) / price if ema20 > 0 else 0
            ema50_dist = (price - ema50) / price if ema50 > 0 else 0

            bb_upper = self._safe(latest.get("bb_upper"), price)
            bb_lower = self._safe(latest.get("bb_lower"), price)
            if bb_upper > bb_lower:
                bb_pctb = (price - bb_lower) / (bb_upper - bb_lower)
            else:
                bb_pctb = 0.5

            vwap = self._safe(latest.get("vwap"), price)
            vwap_dist = (price - vwap) / price if vwap > 0 else 0

            adx = self._safe(latest.get("adx"), 20) / 100  # Normalize 0-1

            atr = self._safe(latest.get("atr"), price * 0.02)
            atr_ratio = atr / price if price > 0 else 0.02

            vol = float(latest.get("volume", 0))
            vol_avg = float(df["volume"].tail(20).mean()) if len(df) >= 20 else vol
            vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
            vol_ratio = min(5.0, vol_ratio)  # Cap

            # Fibonacci proximity
            fib_618 = self._safe(latest.get("fib_618"), 0)
            if fib_618 > 0 and price > 0:
                fib_proximity = 1.0 - min(1.0, abs(price - fib_618) / price * 10)
            else:
                fib_proximity = 0.0

            # --- Regime (one-hot) ---
            regime_trending = 1.0 if regime == "TRENDING" else 0.0
            regime_ranging = 1.0 if regime == "RANGING" else 0.0
            regime_volatile = 1.0 if regime == "VOLATILE" else 0.0

            # --- Macro Risk ---
            macro_map = {"NORMAL": 0.0, "HIGH": 0.5, "CRITICAL": 1.0}
            macro_risk_score = macro_map.get(macro_risk, 0.0)

            # --- Timeframe (one-hot) ---
            tf_15m = 1.0 if timeframe == "15m" else 0.0
            tf_1h = 1.0 if timeframe == "1h" else 0.0
            tf_4h = 1.0 if timeframe == "4h" else 0.0

            # --- Time features (cyclical) ---
            now = datetime.now()
            hour = now.hour + now.minute / 60
            hour_sin = np.sin(2 * np.pi * hour / 24)
            hour_cos = np.cos(2 * np.pi * hour / 24)
            dow = now.weekday()
            dow_sin = np.sin(2 * np.pi * dow / 7)
            dow_cos = np.cos(2 * np.pi * dow / 7)

            # --- Signal scores ---
            bull_score = float(signal.get("bull_score", 0)) / 10  # Normalize
            bear_score = float(signal.get("bear_score", 0)) / 10

            features = np.array([
                rsi, macd_hist_norm, ema20_dist, ema50_dist,
                bb_pctb, vwap_dist, adx, atr_ratio,
                vol_ratio, fib_proximity, regime_trending,
                regime_ranging, regime_volatile, macro_risk_score,
                tf_15m, tf_1h, tf_4h,
                hour_sin, hour_cos, dow_sin, dow_cos,
                bull_score, bear_score,
            ], dtype=np.float64)

            return features

        except Exception as e:
            logger.error(f"[ML] Feature extraction error: {e}")
            return None

    # ==========================================
    #  PREDICTION
    # ==========================================

    def predict(
        self,
        df: pd.DataFrame,
        signal: dict,
        regime: str = "RANGING",
        macro_risk: str = "NORMAL",
        timeframe: str = "1h",
    ) -> dict:
        """
        Du doan confidence score cho signal.

        Returns:
            {
                "confidence": 0.0 - 1.0,
                "rating_adjust": -1 to +2,
                "is_trained": True/False,
                "model_accuracy": 0.0 - 1.0,
                "top_features": [...],
                "_features": [...] | None,  # 23 floats, luu vao position de train sau
            }
        """
        # Extract features TRUOC khi check is_trained: nho vay sample van duoc thu thap
        # ngay tu nhung lenh dau tien (chua co model) -> moi du 30 samples de train.
        # Truoc day return som o day lam feedback loop bi khoa vinh vien.
        self._maybe_reload_from_disk()
        features = self.extract_features(df, signal, regime, macro_risk, timeframe)
        feat_list = features.tolist() if features is not None else None

        if not self.is_trained or self.model is None:
            return {
                "confidence": 0.5,
                "rating_adjust": 0,
                "is_trained": False,
                "model_accuracy": 0,
                "top_features": [],
                "_features": feat_list,  # Van thu thap de train sau nay
                "message": f"ML chua train (can {self.MIN_SAMPLES} trades, hien co {len(self.training_data)})",
            }

        if features is None:
            return {
                "confidence": 0.5, "rating_adjust": 0,
                "is_trained": True, "model_accuracy": self.model_accuracy,
                "top_features": [], "_features": None,
                "message": "Khong the extract features",
            }

        try:
            proba = self.model.predict_proba(features.reshape(1, -1))[0]
            confidence = float(proba[1]) if len(proba) > 1 else 0.5

            # Rating adjust
            if confidence >= self.CONFIDENCE_THRESHOLDS["boost_2"]:
                rating_adjust = 2
            elif confidence >= self.CONFIDENCE_THRESHOLDS["boost_1"]:
                rating_adjust = 1
            elif confidence < self.CONFIDENCE_THRESHOLDS["neutral_low"]:
                rating_adjust = -1
            else:
                rating_adjust = 0

            # Top features
            top_features = sorted(
                self.feature_importance.items(),
                key=lambda x: x[1], reverse=True
            )[:5]

            logger.info(
                f"[ML] Confidence={confidence:.2f} → rating_adjust={rating_adjust:+d} | "
                f"Top: {', '.join(f'{n}={v:.3f}' for n, v in top_features[:3])}"
            )

            return {
                "confidence": round(confidence, 3),
                "rating_adjust": rating_adjust,
                "is_trained": True,
                "model_accuracy": self.model_accuracy,
                "top_features": top_features,
                "_features": features.tolist(),  # 23 floats, cho ML training feedback loop
            }

        except Exception as e:
            logger.error(f"[ML] Prediction error: {e}")
            return {
                "confidence": 0.5, "rating_adjust": 0,
                "is_trained": True, "model_accuracy": self.model_accuracy,
                "top_features": [], "_features": feat_list,
                "message": f"Prediction error: {str(e)[:100]}",
            }

    # ==========================================
    #  TRAINING
    # ==========================================

    def add_training_sample(
        self,
        features: np.ndarray,
        label: int,  # 1 = win, 0 = loss
        pnl: float = 0,
        trade_key: str = "",
    ):
        """Them 1 sample vao training dataset."""
        if features is None or len(features) != len(FEATURE_NAMES):
            return

        sample = {
            "features": features.tolist(),
            "label": label,
            "pnl": pnl,
            "trade_key": trade_key,
            "added_at": datetime.now().isoformat(),
        }
        self.training_data.append(sample)
        self._save_training_data()

        # Check xem co can retrain khong
        new_count = len(self.training_data) - self.last_train_count
        if len(self.training_data) >= self.MIN_SAMPLES and new_count >= self.RETRAIN_THRESHOLD:
            logger.info(f"[ML] Auto-retrain triggered ({new_count} new samples)")
            self.train()

    def train(self) -> dict:
        """
        Train/retrain model tren toan bo training data.
        Su dung LightGBM hoac fallback ve sklearn GradientBoosting.
        """
        if len(self.training_data) < self.MIN_SAMPLES:
            return {
                "success": False,
                "message": f"Can {self.MIN_SAMPLES} samples, hien co {len(self.training_data)}"
            }

        try:
            X = np.array([s["features"] for s in self.training_data])
            y = np.array([s["label"] for s in self.training_data])

            # Kiem tra class balance
            n_pos = int(y.sum())
            n_neg = len(y) - n_pos
            if n_pos < 5 or n_neg < 5:
                return {
                    "success": False,
                    "message": f"Data khong can bang (win={n_pos}, loss={n_neg}). Can them data."
                }

            # Try LightGBM first, fallback to sklearn
            try:
                import lightgbm as lgb
                model = lgb.LGBMClassifier(
                    n_estimators=100,
                    max_depth=5,
                    learning_rate=0.1,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    min_child_samples=5,
                    is_unbalance=True,
                    verbose=-1,
                    random_state=42,
                )
                engine = "LightGBM"
            except ImportError:
                from sklearn.ensemble import GradientBoostingClassifier
                model = GradientBoostingClassifier(
                    n_estimators=100,
                    max_depth=5,
                    learning_rate=0.1,
                    subsample=0.8,
                    min_samples_leaf=5,
                    random_state=42,
                )
                engine = "sklearn-GBM"

            # Cross-validation score
            from sklearn.model_selection import cross_val_score
            scores = cross_val_score(model, X, y, cv=min(5, len(y) // 5), scoring="accuracy")
            avg_accuracy = scores.mean()

            # Train tren toan bo data
            model.fit(X, y)

            # Feature importance
            importances = model.feature_importances_
            self.feature_importance = {
                name: round(float(imp), 4)
                for name, imp in zip(FEATURE_NAMES, importances)
            }

            self.model = model
            self.is_trained = True
            self.model_accuracy = avg_accuracy
            self.last_train_count = len(self.training_data)
            self._save_model()

            logger.success(
                f"[ML] Model trained! Engine={engine} | Accuracy={avg_accuracy:.1%} | "
                f"Samples={len(self.training_data)} | Top features: "
                f"{sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)[:3]}"
            )

            return {
                "success": True,
                "engine": engine,
                "accuracy": round(avg_accuracy, 3),
                "samples": len(self.training_data),
                "feature_importance": self.feature_importance,
                "cv_scores": scores.tolist(),
            }

        except Exception as e:
            logger.error(f"[ML] Training error: {e}")
            return {"success": False, "message": str(e)}

    # ==========================================
    #  STATUS
    # ==========================================

    def get_status(self) -> dict:
        """Tra ve trang thai hien tai cua ML module."""
        self._maybe_reload_from_disk()
        return {
            "is_trained": self.is_trained,
            "model_accuracy": self.model_accuracy,
            "total_samples": len(self.training_data),
            "min_samples_required": self.MIN_SAMPLES,
            "samples_until_train": max(0, self.MIN_SAMPLES - len(self.training_data)),
            "new_samples_since_train": len(self.training_data) - self.last_train_count,
            "retrain_threshold": self.RETRAIN_THRESHOLD,
            "feature_importance": self.feature_importance,
            "thresholds": self.CONFIDENCE_THRESHOLDS,
        }

    @staticmethod
    def _safe(val, fallback: float = 0.0) -> float:
        if val is None:
            return fallback
        try:
            f = float(val)
            if pd.isna(f):
                return fallback
            return f
        except (ValueError, TypeError):
            return fallback


# ==========================================
#  SINGLETON ACCESSOR
# ==========================================

_BOOSTER_INSTANCE: Optional[AdaptiveSignalBooster] = None


def get_booster() -> AdaptiveSignalBooster:
    """
    Tra ve instance dung chung cho ca process.

    Truoc day moi noi (signal_scanner, trade_engine, api/server) tu tao
    AdaptiveSignalBooster() rieng -> state phan manh: scanner khong thay sample moi
    do trade_engine ghi ra, /api/ai/ml/status bao sai total_samples.
    """
    global _BOOSTER_INSTANCE
    if _BOOSTER_INSTANCE is None:
        _BOOSTER_INSTANCE = AdaptiveSignalBooster()
    return _BOOSTER_INSTANCE


def reset_booster():
    """Xoa singleton (dung cho test)."""
    global _BOOSTER_INSTANCE
    _BOOSTER_INSTANCE = None
