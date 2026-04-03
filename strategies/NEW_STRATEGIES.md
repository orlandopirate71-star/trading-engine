# New Algorithmic Trading Strategies

Three new strategies have been added to complement your existing RSI+MACD and Mean Reversion strategies.

## 1. Breakout Momentum Strategy
**File:** `breakout_momentum.py`  
**Class:** `BreakoutMomentumStrategy`

### Description
Catches strong directional moves when price breaks above recent highs or below recent lows with momentum confirmation.

### Entry Logic
**Long:**
- Price breaks above 20-period high
- RSI > 50 (bullish momentum)
- ADX > 25 (trending market)

**Short:**
- Price breaks below 20-period low
- RSI < 50 (bearish momentum)
- ADX > 25 (trending market)

### Risk Management
- Stop Loss: 2x ATR from entry
- Take Profit: 3x ATR from entry (1.5:1 Risk/Reward)
- Cooldown: 10 minutes between signals

### Best For
- Trending forex pairs (EUR/USD, GBP/USD)
- High volatility sessions (London/NY overlap)
- Breakout traders who want to catch momentum

### Parameters
```python
{
    "lookback_period": 20,        # Period to find highs/lows
    "breakout_threshold": 0.0005, # 0.05% above/below for confirmation
    "adx_threshold": 25,          # Minimum ADX for trending
    "stop_loss_atr": 2.0,         # Stop loss in ATR multiples
    "take_profit_atr": 3.0,       # Take profit in ATR multiples
    "cooldown_minutes": 10
}
```

---

## 2. EMA Trend Following Strategy
**File:** `ema_trend_following.py`  
**Class:** `EMATrendFollowingStrategy`

### Description
Rides strong trends using triple EMA alignment (9/21/50) and enters on pullbacks to the fast EMA.

### Entry Logic
**Long:**
- 9 EMA > 21 EMA > 50 EMA (bullish alignment)
- Price pulls back to 9 EMA
- MACD histogram positive
- ADX > 20 (trending)

**Short:**
- 9 EMA < 21 EMA < 50 EMA (bearish alignment)
- Price pulls back to 9 EMA
- MACD histogram negative
- ADX > 20 (trending)

### Risk Management
- Stop Loss: 0.8% or below 21 EMA (dynamic)
- Take Profit: 2.4% (3:1 Risk/Reward)
- Cooldown: 15 minutes between signals

### Best For
- Strong trending markets
- Pairs with clear directional bias
- Trend followers who want to avoid choppy markets

### Parameters
```python
{
    "fast_ema": 9,
    "mid_ema": 21,
    "slow_ema": 50,
    "pullback_threshold": 0.0003, # 0.03% from EMA
    "adx_threshold": 20,
    "stop_loss_pct": 0.008,       # 0.8%
    "take_profit_pct": 0.024,     # 2.4%
    "cooldown_minutes": 15
}
```

---

## 3. Support/Resistance Bounce Strategy
**File:** `support_resistance_bounce.py`  
**Class:** `SupportResistanceBounceStrategy`

### Description
Identifies key support/resistance levels from swing points and trades bounces with candlestick pattern confirmation.

### Entry Logic
**Long:**
- Price approaches support level (within 0.02%)
- RSI < 40 (oversold at support)
- Bullish rejection candle (long lower wick > 60% of candle range)
- Level tested at least 2 times previously

**Short:**
- Price approaches resistance level (within 0.02%)
- RSI > 60 (overbought at resistance)
- Bearish rejection candle (long upper wick > 60% of candle range)
- Level tested at least 2 times previously

### Risk Management
- Stop Loss: 0.6% beyond S/R level
- Take Profit: 1.8% (3:1 Risk/Reward)
- Cooldown: 20 minutes between signals

### Best For
- Range-bound markets
- Pairs respecting key levels
- Counter-trend traders who want high-probability bounces

### Parameters
```python
{
    "lookback_candles": 50,
    "level_threshold": 0.0002,        # 0.02% proximity to level
    "min_touches": 2,                 # Minimum times level was tested
    "wick_ratio": 0.6,                # Wick must be 60% of candle
    "rsi_support_threshold": 40,
    "rsi_resistance_threshold": 60,
    "stop_loss_pct": 0.006,           # 0.6%
    "take_profit_pct": 0.018,         # 1.8%
    "cooldown_minutes": 20
}
```

---

## How to Enable These Strategies

1. **Add to your strategies directory** - Already done ✓

2. **Enable in the dashboard:**
   - Go to Strategies page
   - Toggle ON the strategies you want to use
   - They will start generating signals immediately

3. **Or enable via API:**
```bash
curl -X POST http://localhost:8000/api/strategies/BreakoutMomentumStrategy/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

curl -X POST http://localhost:8000/api/strategies/EMATrendFollowingStrategy/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

curl -X POST http://localhost:8000/api/strategies/SupportResistanceBounceStrategy/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

---

## Strategy Comparison

| Strategy | Type | Best Market | Risk/Reward | Cooldown | Confidence Range |
|----------|------|-------------|-------------|----------|------------------|
| **Breakout Momentum** | Trend | Trending | 1.5:1 | 10 min | 60-95% |
| **EMA Trend Following** | Trend | Strong Trends | 3:1 | 15 min | 65-95% |
| **S/R Bounce** | Counter-trend | Range-bound | 3:1 | 20 min | 65-95% |
| RSI+MACD (existing) | Mean Reversion | Mixed | 2:1 | 3 min | 50-90% |
| Mean Reversion (existing) | Mean Reversion | Range-bound | 1.2:1 | 5 min | 50-85% |

---

## Recommended Strategy Combinations

### Conservative Portfolio (Lower frequency, higher quality)
- EMA Trend Following (trending markets)
- S/R Bounce (range-bound markets)
- AI confidence threshold: 0.80+

### Aggressive Portfolio (Higher frequency, more signals)
- Breakout Momentum
- RSI+MACD
- Mean Reversion
- AI confidence threshold: 0.70+

### Balanced Portfolio (Mix of trend and counter-trend)
- EMA Trend Following
- Breakout Momentum
- S/R Bounce
- AI confidence threshold: 0.75+

---

## Testing Recommendations

1. **Start with paper trading** - Test each strategy individually first
2. **Monitor AI validation** - Check which strategies get approved most by your AI
3. **Track performance** - Use the Performance page to see which strategies perform best
4. **Adjust parameters** - Fine-tune based on your results
5. **Combine strategically** - Use trend-following in trending markets, mean reversion in ranges

---

## Notes

- All strategies integrate with your existing AI validation system
- Signals will be sent to your AI for approval before execution
- Position monitoring will track all trades with screenshots
- Each strategy maintains per-symbol state and cooldowns
- Strategies use the same indicator library as your existing strategies
