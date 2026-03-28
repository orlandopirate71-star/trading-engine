"""
Trade executor - handles order placement and position management.
Supports multiple broker APIs (starting with Binance).
"""
import time
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum
import threading

from models import Trade, Position, TradeStatus, TradeDirection
from connections import get_db_connection


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    TAKE_PROFIT_MARKET = "take_profit_market"


@dataclass
class OrderResult:
    """Result of an order execution."""
    success: bool
    order_id: Optional[str] = None
    filled_price: float = 0.0
    filled_quantity: float = 0.0
    fees: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = None


class BrokerAPI:
    """
    Base class for broker API integrations.
    Override methods for specific broker implementations.
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to the broker API."""
        raise NotImplementedError
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> OrderResult:
        """Place a market order."""
        raise NotImplementedError
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> OrderResult:
        """Place a limit order."""
        raise NotImplementedError
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        raise NotImplementedError
    
    def get_position(self, symbol: str) -> Optional[dict]:
        """Get current position for a symbol."""
        raise NotImplementedError
    
    def get_balance(self) -> dict:
        """Get account balance."""
        raise NotImplementedError


class PaperBroker(BrokerAPI):
    """
    Paper trading broker for testing strategies without real money.
    """
    
    def __init__(self, initial_balance: float = 10000.0):
        super().__init__(testnet=True)
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions: Dict[str, dict] = {}
        self.orders: List[dict] = []
        self.order_counter = 0
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        self.connected = True
        print("[PAPER] Paper trading broker connected")
        return True
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> OrderResult:
        """Simulate a market order."""
        with self._lock:
            self.order_counter += 1
            order_id = f"PAPER_{self.order_counter}"
            
            # Get current price from Redis
            from connections import redis_client
            price_str = redis_client.get("latest_price")
            if not price_str:
                return OrderResult(
                    success=False,
                    error="No price data available"
                )
            
            price = float(price_str)
            cost = price * quantity
            fees = cost * 0.001  # 0.1% fee simulation
            
            # Check balance for buys
            if side.upper() == "BUY":
                if cost + fees > self.balance:
                    return OrderResult(
                        success=False,
                        error=f"Insufficient balance: need {cost + fees}, have {self.balance}"
                    )
                self.balance -= (cost + fees)
            
            # Update position
            if symbol not in self.positions:
                self.positions[symbol] = {
                    "quantity": 0.0,
                    "avg_price": 0.0,
                    "side": None
                }
            
            pos = self.positions[symbol]
            if side.upper() == "BUY":
                # Add to long position
                total_qty = pos["quantity"] + quantity
                if pos["quantity"] > 0:
                    pos["avg_price"] = (
                        (pos["avg_price"] * pos["quantity"]) + (price * quantity)
                    ) / total_qty
                else:
                    pos["avg_price"] = price
                pos["quantity"] = total_qty
                pos["side"] = "LONG"
            else:
                # Close or reduce position
                if pos["quantity"] >= quantity:
                    pnl = (price - pos["avg_price"]) * quantity
                    self.balance += (price * quantity) - fees + pnl
                    pos["quantity"] -= quantity
                    if pos["quantity"] == 0:
                        pos["side"] = None
                        pos["avg_price"] = 0.0
            
            order = {
                "id": order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "fees": fees,
                "timestamp": datetime.utcnow()
            }
            self.orders.append(order)
            
            print(f"[PAPER] {side} {quantity} {symbol} @ {price} (fees: {fees:.4f})")
            
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=price,
                filled_quantity=quantity,
                fees=fees,
                timestamp=datetime.utcnow()
            )
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> OrderResult:
        """For paper trading, treat limit orders as market orders."""
        return self.place_market_order(symbol, side, quantity)
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        return True
    
    def get_position(self, symbol: str) -> Optional[dict]:
        return self.positions.get(symbol)
    
    def get_balance(self) -> dict:
        return {
            "total": self.balance,
            "available": self.balance,
            "initial": self.initial_balance,
            "pnl": self.balance - self.initial_balance,
            "pnl_percent": ((self.balance - self.initial_balance) / self.initial_balance) * 100
        }
    
    def get_all_positions(self) -> dict:
        return {k: v for k, v in self.positions.items() if v["quantity"] > 0}


class TradeExecutor:
    """
    Manages trade execution and position tracking.
    """
    
    def __init__(self, broker: BrokerAPI = None):
        self.broker = broker or PaperBroker()
        self.open_positions: Dict[int, Position] = {}  # trade_id -> Position
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        """Connect to the broker."""
        return self.broker.connect()
    
    def execute_trade(self, trade: Trade, quantity: float = 0.01) -> Trade:
        """
        Execute a trade that has been approved.
        """
        if trade.status not in [TradeStatus.APPROVED, "approved"]:
            trade.status = TradeStatus.FAILED
            trade.metadata["error"] = "Trade not approved"
            return trade
        
        # Determine order side
        side = "BUY" if trade.direction == TradeDirection.LONG else "SELL"
        
        # Place the order
        result = self.broker.place_market_order(
            symbol=trade.symbol,
            side=side,
            quantity=quantity
        )
        
        if result.success:
            trade.status = TradeStatus.OPEN
            trade.entry_price = result.filled_price
            trade.quantity = result.filled_quantity
            trade.fees = result.fees
            trade.entry_time = result.timestamp
            trade.metadata["order_id"] = result.order_id
            
            # Create position record
            position = Position(
                trade_id=trade.id,
                symbol=trade.symbol,
                direction=trade.direction,
                entry_price=result.filled_price,
                quantity=result.filled_quantity,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                current_price=result.filled_price,
                unrealized_pnl=0.0,
                trailing_stop_trigger=trade.trailing_stop_trigger,
                trailing_stop_lock=trade.trailing_stop_lock,
                trailing_stop_activated=False
            )
            
            with self._lock:
                self.open_positions[trade.id] = position
            
            print(f"[EXECUTOR] Opened {trade.direction.value} position: {trade.symbol} @ {result.filled_price}")
        else:
            trade.status = TradeStatus.FAILED
            trade.metadata["error"] = result.error
            print(f"[EXECUTOR] Failed to execute trade: {result.error}")
        
        return trade
    
    def close_position(self, trade_id: int, reason: str = "manual") -> Optional[Trade]:
        """
        Close an open position.
        """
        with self._lock:
            if trade_id not in self.open_positions:
                print(f"[EXECUTOR] No open position for trade {trade_id}")
                return None
            
            position = self.open_positions[trade_id]
        
        # Determine close side (opposite of entry)
        side = "SELL" if position.direction == TradeDirection.LONG else "BUY"
        
        result = self.broker.place_market_order(
            symbol=position.symbol,
            side=side,
            quantity=position.quantity
        )
        
        if result.success:
            # Calculate P&L
            if position.direction == TradeDirection.LONG:
                pnl = (result.filled_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - result.filled_price) * position.quantity
            
            pnl -= result.fees  # Subtract exit fees
            pnl_percent = (pnl / (position.entry_price * position.quantity)) * 100
            
            with self._lock:
                del self.open_positions[trade_id]
            
            print(f"[EXECUTOR] Closed position {trade_id}: P&L = {pnl:.4f} ({pnl_percent:.2f}%)")
            
            # Return trade update info
            return {
                "trade_id": trade_id,
                "exit_price": result.filled_price,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "fees": result.fees,
                "exit_time": result.timestamp,
                "close_reason": reason
            }
        
        return None
    
    def check_stop_loss_take_profit(self, current_prices: Dict[str, float]):
        """
        Check all open positions for stop loss, take profit, or trailing stop triggers.
        """
        positions_to_close = []

        with self._lock:
            for trade_id, position in self.open_positions.items():
                price = current_prices.get(position.symbol)
                if not price:
                    continue

                position.current_price = price

                # Calculate unrealized P&L
                if position.direction == TradeDirection.LONG:
                    position.unrealized_pnl = (price - position.entry_price) * position.quantity

                    # Check trailing stop activation
                    if (position.trailing_stop_trigger and
                        not position.trailing_stop_activated and
                        position.unrealized_pnl >= position.trailing_stop_trigger):
                        # Activate trailing stop - move SL to lock in profit
                        profit_per_unit = position.trailing_stop_lock / position.quantity
                        position.stop_loss = position.entry_price + profit_per_unit
                        position.trailing_stop_activated = True
                        print(f"[EXECUTOR] Trailing stop ACTIVATED: trade {trade_id}, new SL={position.stop_loss:.5f}")

                    # Check stop loss (original or trailing)
                    if position.stop_loss and price <= position.stop_loss:
                        reason = "trailing_stop" if position.trailing_stop_activated else "stop_loss"
                        positions_to_close.append((trade_id, reason))
                    # Check take profit
                    elif position.take_profit and price >= position.take_profit:
                        positions_to_close.append((trade_id, "take_profit"))
                else:
                    position.unrealized_pnl = (position.entry_price - price) * position.quantity

                    # Check trailing stop activation
                    if (position.trailing_stop_trigger and
                        not position.trailing_stop_activated and
                        position.unrealized_pnl >= position.trailing_stop_trigger):
                        # Activate trailing stop - move SL to lock in profit
                        profit_per_unit = position.trailing_stop_lock / position.quantity
                        position.stop_loss = position.entry_price - profit_per_unit
                        position.trailing_stop_activated = True
                        print(f"[EXECUTOR] Trailing stop ACTIVATED: trade {trade_id}, new SL={position.stop_loss:.5f}")

                    # Check stop loss (for shorts, price going up)
                    if position.stop_loss and price >= position.stop_loss:
                        reason = "trailing_stop" if position.trailing_stop_activated else "stop_loss"
                        positions_to_close.append((trade_id, reason))
                    # Check take profit (for shorts, price going down)
                    elif position.take_profit and price <= position.take_profit:
                        positions_to_close.append((trade_id, "take_profit"))

        # Close triggered positions
        results = []
        for trade_id, reason in positions_to_close:
            result = self.close_position(trade_id, reason)
            if result:
                results.append(result)

        return results
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        with self._lock:
            return list(self.open_positions.values())
    
    def get_balance(self) -> dict:
        """Get current account balance."""
        return self.broker.get_balance()


# Singleton instance
_executor: Optional[TradeExecutor] = None


def get_executor(broker: BrokerAPI = None) -> TradeExecutor:
    """Get or create the trade executor singleton."""
    global _executor
    if _executor is None:
        _executor = TradeExecutor(broker)
    return _executor
