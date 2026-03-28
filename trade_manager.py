"""
Trade Manager - Manages all open trades with actions like:
- Moving stop losses
- Moving take profits
- Closing trades (full or partial)
- Trailing stops
- Break-even stops
"""
import json
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import Enum

from connections import get_db_connection, redis_client
from models import Trade, TradeDirection, TradeStatus


class TradeAction(Enum):
    MOVE_STOP = "move_stop"
    MOVE_TP = "move_tp"
    CLOSE = "close"
    PARTIAL_CLOSE = "partial_close"
    BREAK_EVEN = "break_even"
    TRAILING_STOP = "trailing_stop"


@dataclass
class OpenPosition:
    """Represents an open position with current market data."""
    trade_id: int
    symbol: str
    direction: TradeDirection
    entry_price: float
    quantity: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    opened_at: datetime
    strategy_name: str
    # Trailing stop settings
    trailing_stop_trigger: Optional[float] = None  # Profit ($) to trigger
    trailing_stop_lock: Optional[float] = None      # Profit ($) to lock
    trailing_stop_activated: bool = False
    
    @property
    def is_profitable(self) -> bool:
        return self.unrealized_pnl > 0
    
    @property
    def risk_reward_current(self) -> Optional[float]:
        """Current R:R based on entry, current price, and stop."""
        if not self.stop_loss:
            return None
        if self.direction == TradeDirection.LONG:
            risk = self.entry_price - self.stop_loss
            reward = self.current_price - self.entry_price
        else:
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - self.current_price
        if risk <= 0:
            return None
        return reward / risk


class TradeManager:
    """Manages all open trades and provides trade management actions."""
    
    def __init__(self, executor=None):
        self.executor = executor
        self._trailing_stops: Dict[int, dict] = {}  # trade_id -> trailing config
    
    def get_open_positions(self) -> List[OpenPosition]:
        """Get all open positions with current P&L."""
        positions = []
        
        # Get current prices
        prices = redis_client.hgetall("latest_prices")
        current_prices = {k: float(v) for k, v in prices.items()}
        
        # Get open trades from database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, strategy_name, symbol, direction, entry_price,
                   stop_loss, take_profit, quantity, entry_time,
                   trailing_stop_trigger, trailing_stop_lock, trailing_stop_activated
            FROM trades
            WHERE status = 'open'
            ORDER BY entry_time DESC
        """)

        for row in cursor.fetchall():
            trade_id, strategy, symbol, direction, entry_price, sl, tp, qty, entry_time, ts_trigger, ts_lock, ts_activated = row

            # Convert Decimal to float
            entry_price = float(entry_price) if entry_price else 0
            sl = float(sl) if sl else None
            tp = float(tp) if tp else None
            qty = float(qty) if qty else 0
            ts_trigger = float(ts_trigger) if ts_trigger else None
            ts_lock = float(ts_lock) if ts_lock else None
            
            # Get current price
            current_price = current_prices.get(symbol, entry_price)
            
            # Calculate P&L
            direction_enum = TradeDirection.LONG if direction == 'long' else TradeDirection.SHORT
            if direction_enum == TradeDirection.LONG:
                pnl = (current_price - entry_price) * qty
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            else:
                pnl = (entry_price - current_price) * qty
                pnl_pct = ((entry_price - current_price) / entry_price) * 100 if entry_price > 0 else 0
            
            # Handle entry_time - could be datetime object or string
            if entry_time:
                if isinstance(entry_time, str):
                    opened_at = datetime.fromisoformat(entry_time)
                else:
                    opened_at = entry_time
            else:
                opened_at = datetime.utcnow()
            
            positions.append(OpenPosition(
                trade_id=trade_id,
                symbol=symbol,
                direction=direction_enum,
                entry_price=entry_price,
                quantity=qty,
                stop_loss=sl,
                take_profit=tp,
                current_price=current_price,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                opened_at=opened_at,
                strategy_name=strategy,
                trailing_stop_trigger=ts_trigger,
                trailing_stop_lock=ts_lock,
                trailing_stop_activated=bool(ts_activated)
            ))
        
        conn.close()
        return positions
    
    def get_position(self, trade_id: int) -> Optional[OpenPosition]:
        """Get a single position by trade ID."""
        positions = self.get_open_positions()
        for pos in positions:
            if pos.trade_id == trade_id:
                return pos
        return None
    
    def move_stop_loss(self, trade_id: int, new_stop: float) -> Tuple[bool, str]:
        """Move stop loss for a trade."""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current trade
        cursor.execute("SELECT symbol, direction, entry_price, stop_loss FROM trades WHERE id = %s", (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Trade not found"
        
        symbol, direction, entry_price, old_stop = row
        
        # Validate new stop
        if direction == 'long' and new_stop >= entry_price:
            # Allow stop above entry (profit lock)
            pass
        elif direction == 'short' and new_stop <= entry_price:
            # Allow stop below entry (profit lock)
            pass
        
        # Update in database
        cursor.execute("UPDATE trades SET stop_loss = %s WHERE id = %s", (new_stop, trade_id))
        conn.commit()
        conn.close()
        
        # Update in executor if available
        if self.executor:
            self.executor.update_stop_loss(trade_id, new_stop)
        
        return True, f"Stop loss moved from {old_stop:.5f} to {new_stop:.5f}"
    
    def move_take_profit(self, trade_id: int, new_tp: float) -> Tuple[bool, str]:
        """Move take profit for a trade."""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT take_profit FROM trades WHERE id = %s", (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Trade not found"
        
        old_tp = row[0]
        
        cursor.execute("UPDATE trades SET take_profit = %s WHERE id = %s", (new_tp, trade_id))
        conn.commit()
        conn.close()
        
        if self.executor:
            self.executor.update_take_profit(trade_id, new_tp)
        
        return True, f"Take profit moved from {old_tp:.5f} to {new_tp:.5f}"
    
    def set_break_even(self, trade_id: int, offset_pips: float = 0) -> Tuple[bool, str]:
        """Move stop loss to break even (entry price + offset)."""
        pos = self.get_position(trade_id)
        if not pos:
            return False, "Position not found"
        
        # Calculate break-even stop
        pip_value = 0.0001 if 'JPY' not in pos.symbol else 0.01
        offset = offset_pips * pip_value
        
        if pos.direction == TradeDirection.LONG:
            new_stop = pos.entry_price + offset
        else:
            new_stop = pos.entry_price - offset
        
        return self.move_stop_loss(trade_id, new_stop)
    
    def close_trade(self, trade_id: int, reason: str = "Manual close") -> Tuple[bool, str]:
        """Close a trade at current market price."""
        pos = self.get_position(trade_id)
        if not pos:
            return False, "Position not found"
        
        # Close via executor
        if self.executor:
            result = self.executor.close_position(trade_id, pos.current_price, reason)
            if result:
                return True, f"Trade {trade_id} closed at {pos.current_price:.5f}, P&L: {pos.unrealized_pnl:.2f}"
        
        # Fallback: update database directly
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE trades 
            SET status = 'closed', 
                exit_price = %s, 
                exit_time = %s,
                pnl = %s
            WHERE id = %s
        """, (pos.current_price, datetime.utcnow().isoformat(), pos.unrealized_pnl, trade_id))
        conn.commit()
        conn.close()
        
        return True, f"Trade {trade_id} closed at {pos.current_price:.5f}, P&L: {pos.unrealized_pnl:.2f}"
    
    def close_all_trades(self, symbol: str = None, reason: str = "Close all") -> Tuple[int, str]:
        """Close all open trades, optionally filtered by symbol."""
        positions = self.get_open_positions()
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        
        closed = 0
        total_pnl = 0
        
        for pos in positions:
            success, _ = self.close_trade(pos.trade_id, reason)
            if success:
                closed += 1
                total_pnl += pos.unrealized_pnl
        
        return closed, f"Closed {closed} trades, total P&L: {total_pnl:.2f}"
    
    def enable_trailing_stop(self, trade_id: int, trail_pips: float, activation_pips: float = 0) -> Tuple[bool, str]:
        """Enable trailing stop for a trade."""
        pos = self.get_position(trade_id)
        if not pos:
            return False, "Position not found"
        
        pip_value = 0.0001 if 'JPY' not in pos.symbol else 0.01
        
        self._trailing_stops[trade_id] = {
            "trail_distance": trail_pips * pip_value,
            "activation_distance": activation_pips * pip_value,
            "highest_price": pos.current_price if pos.direction == TradeDirection.LONG else None,
            "lowest_price": pos.current_price if pos.direction == TradeDirection.SHORT else None,
            "activated": activation_pips == 0
        }
        
        return True, f"Trailing stop enabled: {trail_pips} pips, activates at {activation_pips} pips profit"
    
    def disable_trailing_stop(self, trade_id: int) -> Tuple[bool, str]:
        """Disable trailing stop for a trade."""
        if trade_id in self._trailing_stops:
            del self._trailing_stops[trade_id]

        # Also clear from position if exists
        pos = self.get_position(trade_id)
        if pos:
            pos.trailing_stop_trigger = None
            pos.trailing_stop_lock = None
            pos.trailing_stop_activated = False
            self._update_position_trailing_stop(trade_id, None, None, False)

        return True, "Trailing stop disabled"

    def set_trailing_stop_dollar(self, trade_id: int, trigger_profit: float, lock_profit: float) -> Tuple[bool, str]:
        """Set trailing stop using dollar profit amounts."""
        pos = self.get_position(trade_id)
        if not pos:
            return False, "Position not found"

        if trigger_profit <= 0 or lock_profit <= 0:
            return False, "Trigger and lock profit must be positive"

        if lock_profit > trigger_profit:
            return False, "Lock profit cannot exceed trigger profit"

        # Store on the position
        pos.trailing_stop_trigger = trigger_profit
        pos.trailing_stop_lock = lock_profit
        pos.trailing_stop_activated = False

        # Persist to DB
        self._update_position_trailing_stop(trade_id, trigger_profit, lock_profit, False)

        return True, f"Trailing stop set: trigger at ${trigger_profit:.2f} profit, lock ${lock_profit:.2f}"

    def _update_position_trailing_stop(self, trade_id: int, trigger: Optional[float], lock: Optional[float], activated: bool):
        """Update trailing stop fields in database."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE trades
                SET trailing_stop_trigger = %s,
                    trailing_stop_lock = %s,
                    trailing_stop_activated = %s
                WHERE id = %s
            """, (trigger, lock, activated, trade_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[TM] Failed to update trailing stop in DB: {e}")

    def update_trailing_stops(self, prices: Dict[str, float]):
        """Update all trailing stops based on current prices. Call this on each tick."""
        for trade_id, config in list(self._trailing_stops.items()):
            pos = self.get_position(trade_id)
            if not pos:
                del self._trailing_stops[trade_id]
                continue
            
            current_price = prices.get(pos.symbol, pos.current_price)
            trail_distance = config["trail_distance"]
            activation_distance = config["activation_distance"]
            
            if pos.direction == TradeDirection.LONG:
                # Check activation
                if not config["activated"]:
                    if current_price >= pos.entry_price + activation_distance:
                        config["activated"] = True
                        config["highest_price"] = current_price
                
                if config["activated"]:
                    # Update highest price
                    if current_price > config["highest_price"]:
                        config["highest_price"] = current_price
                        new_stop = current_price - trail_distance
                        if pos.stop_loss is None or new_stop > pos.stop_loss:
                            self.move_stop_loss(trade_id, new_stop)
            else:
                # Short position
                if not config["activated"]:
                    if current_price <= pos.entry_price - activation_distance:
                        config["activated"] = True
                        config["lowest_price"] = current_price
                
                if config["activated"]:
                    if current_price < config["lowest_price"]:
                        config["lowest_price"] = current_price
                        new_stop = current_price + trail_distance
                        if pos.stop_loss is None or new_stop < pos.stop_loss:
                            self.move_stop_loss(trade_id, new_stop)
    
    def get_summary(self) -> dict:
        """Get summary of all open positions."""
        positions = self.get_open_positions()
        
        total_pnl = sum(p.unrealized_pnl for p in positions)
        winning = sum(1 for p in positions if p.unrealized_pnl > 0)
        losing = sum(1 for p in positions if p.unrealized_pnl < 0)
        
        by_symbol = {}
        for p in positions:
            if p.symbol not in by_symbol:
                by_symbol[p.symbol] = {"count": 0, "pnl": 0, "long": 0, "short": 0}
            by_symbol[p.symbol]["count"] += 1
            by_symbol[p.symbol]["pnl"] += p.unrealized_pnl
            if p.direction == TradeDirection.LONG:
                by_symbol[p.symbol]["long"] += 1
            else:
                by_symbol[p.symbol]["short"] += 1
        
        return {
            "total_positions": len(positions),
            "total_unrealized_pnl": total_pnl,
            "winning_positions": winning,
            "losing_positions": losing,
            "by_symbol": by_symbol,
            "trailing_stops_active": len(self._trailing_stops)
        }


# Singleton instance
_trade_manager: TradeManager = None


def get_trade_manager(executor=None) -> TradeManager:
    """Get or create the trade manager singleton."""
    global _trade_manager
    if _trade_manager is None:
        _trade_manager = TradeManager(executor)
    elif executor and _trade_manager.executor is None:
        _trade_manager.executor = executor
    return _trade_manager
