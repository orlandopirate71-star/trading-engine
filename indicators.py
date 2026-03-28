"""
Technical Indicators Library for Trading Strategies

Usage in strategies:
    from indicators import Indicators
    
    class MyStrategy(BaseStrategy):
        def __init__(self):
            self.ind = Indicators()
        
        def on_tick(self, symbol, price, timestamp):
            self.ind.add(price)
            
            sma = self.ind.sma(20)
            rsi = self.ind.rsi(14)
            macd, signal, hist = self.ind.macd()
"""
import math
from typing import List, Optional, Tuple
from dataclasses import dataclass
from collections import deque


@dataclass
class OHLC:
    """Single candlestick/bar."""
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    timestamp: float = 0


class Indicators:
    """
    Technical indicators calculator.
    Maintains price history and computes indicators on demand.
    """
    
    def __init__(self, max_history: int = 500):
        self.prices: deque = deque(maxlen=max_history)
        self.highs: deque = deque(maxlen=max_history)
        self.lows: deque = deque(maxlen=max_history)
        self.volumes: deque = deque(maxlen=max_history)
        self.max_history = max_history
    
    def add(self, price: float, high: float = None, low: float = None, volume: float = 0):
        """Add a new price point."""
        self.prices.append(price)
        self.highs.append(high if high is not None else price)
        self.lows.append(low if low is not None else price)
        self.volumes.append(volume)
    
    def add_ohlc(self, ohlc: OHLC):
        """Add OHLC bar."""
        self.prices.append(ohlc.close)
        self.highs.append(ohlc.high)
        self.lows.append(ohlc.low)
        self.volumes.append(ohlc.volume)
    
    @property
    def count(self) -> int:
        """Number of price points."""
        return len(self.prices)
    
    @property
    def last(self) -> Optional[float]:
        """Last price."""
        return self.prices[-1] if self.prices else None
    
    def clear(self):
        """Clear all history."""
        self.prices.clear()
        self.highs.clear()
        self.lows.clear()
        self.volumes.clear()
    
    # === Moving Averages ===
    
    def sma(self, period: int) -> Optional[float]:
        """Simple Moving Average."""
        if len(self.prices) < period:
            return None
        return sum(list(self.prices)[-period:]) / period
    
    def ema(self, period: int) -> Optional[float]:
        """Exponential Moving Average."""
        if len(self.prices) < period:
            return None
        
        prices = list(self.prices)
        multiplier = 2 / (period + 1)
        
        # Start with SMA for first EMA value
        ema = sum(prices[:period]) / period
        
        # Calculate EMA for remaining prices
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def wma(self, period: int) -> Optional[float]:
        """Weighted Moving Average."""
        if len(self.prices) < period:
            return None
        
        prices = list(self.prices)[-period:]
        weights = list(range(1, period + 1))
        weighted_sum = sum(p * w for p, w in zip(prices, weights))
        return weighted_sum / sum(weights)
    
    def smma(self, period: int) -> Optional[float]:
        """Smoothed Moving Average (used in RSI)."""
        if len(self.prices) < period:
            return None
        
        prices = list(self.prices)
        smma = sum(prices[:period]) / period
        
        for price in prices[period:]:
            smma = (smma * (period - 1) + price) / period
        
        return smma
    
    # === Momentum Indicators ===
    
    def rsi(self, period: int = 14) -> Optional[float]:
        """Relative Strength Index (0-100)."""
        if len(self.prices) < period + 1:
            return None
        
        prices = list(self.prices)
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return None
        
        # First average
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        # Smoothed averages
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def stochastic(self, k_period: int = 14, d_period: int = 3) -> Tuple[Optional[float], Optional[float]]:
        """Stochastic Oscillator. Returns (%K, %D)."""
        if len(self.prices) < k_period:
            return None, None
        
        prices = list(self.prices)
        highs = list(self.highs)
        lows = list(self.lows)
        
        # Calculate %K values
        k_values = []
        for i in range(k_period - 1, len(prices)):
            period_high = max(highs[i-k_period+1:i+1])
            period_low = min(lows[i-k_period+1:i+1])
            
            if period_high == period_low:
                k_values.append(50)
            else:
                k = 100 * (prices[i] - period_low) / (period_high - period_low)
                k_values.append(k)
        
        if not k_values:
            return None, None
        
        k = k_values[-1]
        
        # %D is SMA of %K
        if len(k_values) >= d_period:
            d = sum(k_values[-d_period:]) / d_period
        else:
            d = k
        
        return k, d
    
    def cci(self, period: int = 20) -> Optional[float]:
        """Commodity Channel Index."""
        if len(self.prices) < period:
            return None
        
        # Typical price = (H + L + C) / 3
        tp_list = []
        for i in range(-period, 0):
            tp = (self.highs[i] + self.lows[i] + self.prices[i]) / 3
            tp_list.append(tp)
        
        tp_sma = sum(tp_list) / period
        
        # Mean deviation
        mean_dev = sum(abs(tp - tp_sma) for tp in tp_list) / period
        
        if mean_dev == 0:
            return 0
        
        current_tp = (self.highs[-1] + self.lows[-1] + self.prices[-1]) / 3
        return (current_tp - tp_sma) / (0.015 * mean_dev)
    
    def williams_r(self, period: int = 14) -> Optional[float]:
        """Williams %R (-100 to 0)."""
        if len(self.prices) < period:
            return None
        
        highest = max(list(self.highs)[-period:])
        lowest = min(list(self.lows)[-period:])
        
        if highest == lowest:
            return -50
        
        return -100 * (highest - self.prices[-1]) / (highest - lowest)
    
    def momentum(self, period: int = 10) -> Optional[float]:
        """Price Momentum."""
        if len(self.prices) <= period:
            return None
        return self.prices[-1] - self.prices[-period - 1]
    
    def roc(self, period: int = 10) -> Optional[float]:
        """Rate of Change (%)."""
        if len(self.prices) <= period:
            return None
        old_price = self.prices[-period - 1]
        if old_price == 0:
            return None
        return ((self.prices[-1] - old_price) / old_price) * 100
    
    # === Trend Indicators ===
    
    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """MACD. Returns (macd_line, signal_line, histogram)."""
        if len(self.prices) < slow + signal:
            return None, None, None
        
        prices = list(self.prices)
        
        # Calculate EMAs
        def calc_ema(data, period):
            multiplier = 2 / (period + 1)
            ema = sum(data[:period]) / period
            for price in data[period:]:
                ema = (price - ema) * multiplier + ema
            return ema
        
        # We need to calculate MACD line for enough periods to get signal line
        macd_values = []
        for i in range(slow - 1, len(prices)):
            subset = prices[:i + 1]
            if len(subset) >= slow:
                fast_ema = calc_ema(subset, fast)
                slow_ema = calc_ema(subset, slow)
                macd_values.append(fast_ema - slow_ema)
        
        if len(macd_values) < signal:
            return macd_values[-1] if macd_values else None, None, None
        
        macd_line = macd_values[-1]
        
        # Signal line is EMA of MACD
        multiplier = 2 / (signal + 1)
        signal_ema = sum(macd_values[:signal]) / signal
        for m in macd_values[signal:]:
            signal_ema = (m - signal_ema) * multiplier + signal_ema
        
        signal_line = signal_ema
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def adx(self, period: int = 14) -> Optional[float]:
        """Average Directional Index (trend strength)."""
        if len(self.prices) < period * 2:
            return None
        
        prices = list(self.prices)
        highs = list(self.highs)
        lows = list(self.lows)
        
        # Calculate +DM, -DM, TR
        plus_dm = []
        minus_dm = []
        tr_list = []
        
        for i in range(1, len(prices)):
            high_diff = highs[i] - highs[i-1]
            low_diff = lows[i-1] - lows[i]
            
            plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
            minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
            
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prices[i-1]),
                abs(lows[i] - prices[i-1])
            )
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return None
        
        # Smoothed averages
        def smooth(data, period):
            result = sum(data[:period])
            smoothed = [result]
            for i in range(period, len(data)):
                result = result - result/period + data[i]
                smoothed.append(result)
            return smoothed
        
        smooth_tr = smooth(tr_list, period)
        smooth_plus = smooth(plus_dm, period)
        smooth_minus = smooth(minus_dm, period)
        
        # +DI, -DI
        dx_values = []
        for i in range(len(smooth_tr)):
            if smooth_tr[i] == 0:
                continue
            plus_di = 100 * smooth_plus[i] / smooth_tr[i]
            minus_di = 100 * smooth_minus[i] / smooth_tr[i]
            
            di_sum = plus_di + minus_di
            if di_sum > 0:
                dx = 100 * abs(plus_di - minus_di) / di_sum
                dx_values.append(dx)
        
        if len(dx_values) < period:
            return None
        
        # ADX is smoothed DX
        adx = sum(dx_values[:period]) / period
        for dx in dx_values[period:]:
            adx = (adx * (period - 1) + dx) / period
        
        return adx
    
    # === Volatility Indicators ===
    
    def bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Bollinger Bands. Returns (upper, middle, lower)."""
        if len(self.prices) < period:
            return None, None, None
        
        prices = list(self.prices)[-period:]
        middle = sum(prices) / period
        
        variance = sum((p - middle) ** 2 for p in prices) / period
        std = math.sqrt(variance)
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    def atr(self, period: int = 14) -> Optional[float]:
        """Average True Range."""
        if len(self.prices) < period + 1:
            return None
        
        prices = list(self.prices)
        highs = list(self.highs)
        lows = list(self.lows)
        
        tr_list = []
        for i in range(1, len(prices)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prices[i-1]),
                abs(lows[i] - prices[i-1])
            )
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return None
        
        # Smoothed ATR
        atr = sum(tr_list[:period]) / period
        for tr in tr_list[period:]:
            atr = (atr * (period - 1) + tr) / period
        
        return atr
    
    def std_dev(self, period: int = 20) -> Optional[float]:
        """Standard Deviation."""
        if len(self.prices) < period:
            return None
        
        prices = list(self.prices)[-period:]
        mean = sum(prices) / period
        variance = sum((p - mean) ** 2 for p in prices) / period
        return math.sqrt(variance)
    
    # === Volume Indicators ===
    
    def obv(self) -> Optional[float]:
        """On-Balance Volume."""
        if len(self.prices) < 2:
            return None
        
        prices = list(self.prices)
        volumes = list(self.volumes)
        
        obv = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                obv += volumes[i]
            elif prices[i] < prices[i-1]:
                obv -= volumes[i]
        
        return obv
    
    def vwap(self) -> Optional[float]:
        """Volume Weighted Average Price."""
        if not self.prices or not any(self.volumes):
            return None
        
        prices = list(self.prices)
        volumes = list(self.volumes)
        
        # Typical price * volume
        cumulative_tpv = 0
        cumulative_vol = 0
        
        for i in range(len(prices)):
            tp = (self.highs[i] + self.lows[i] + prices[i]) / 3
            cumulative_tpv += tp * volumes[i]
            cumulative_vol += volumes[i]
        
        if cumulative_vol == 0:
            return None
        
        return cumulative_tpv / cumulative_vol
    
    # === Support/Resistance ===
    
    def pivot_points(self) -> dict:
        """Calculate pivot points from last complete period."""
        if len(self.prices) < 2:
            return {}
        
        high = self.highs[-1]
        low = self.lows[-1]
        close = self.prices[-1]
        
        pivot = (high + low + close) / 3
        
        return {
            'pivot': pivot,
            'r1': 2 * pivot - low,
            'r2': pivot + (high - low),
            'r3': high + 2 * (pivot - low),
            's1': 2 * pivot - high,
            's2': pivot - (high - low),
            's3': low - 2 * (high - pivot)
        }
    
    # === Pattern Detection ===
    
    def is_crossover(self, fast_period: int, slow_period: int) -> bool:
        """Check if fast MA crossed above slow MA."""
        if len(self.prices) < slow_period + 1:
            return False
        
        # Current values
        fast_now = self.sma(fast_period)
        slow_now = self.sma(slow_period)
        
        # Previous values (remove last price temporarily)
        last = self.prices.pop()
        fast_prev = self.sma(fast_period)
        slow_prev = self.sma(slow_period)
        self.prices.append(last)
        
        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return False
        
        return fast_prev <= slow_prev and fast_now > slow_now
    
    def is_crossunder(self, fast_period: int, slow_period: int) -> bool:
        """Check if fast MA crossed below slow MA."""
        if len(self.prices) < slow_period + 1:
            return False
        
        fast_now = self.sma(fast_period)
        slow_now = self.sma(slow_period)
        
        last = self.prices.pop()
        fast_prev = self.sma(fast_period)
        slow_prev = self.sma(slow_period)
        self.prices.append(last)
        
        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return False
        
        return fast_prev >= slow_prev and fast_now < slow_now
    
    def is_overbought(self, rsi_threshold: float = 70) -> bool:
        """Check if RSI indicates overbought."""
        rsi = self.rsi()
        return rsi is not None and rsi > rsi_threshold
    
    def is_oversold(self, rsi_threshold: float = 30) -> bool:
        """Check if RSI indicates oversold."""
        rsi = self.rsi()
        return rsi is not None and rsi < rsi_threshold
    
    def trend_direction(self, period: int = 20) -> str:
        """Get trend direction based on price vs SMA."""
        sma = self.sma(period)
        if sma is None or self.last is None:
            return "neutral"
        
        diff_pct = (self.last - sma) / sma * 100
        
        if diff_pct > 1:
            return "bullish"
        elif diff_pct < -1:
            return "bearish"
        return "neutral"
