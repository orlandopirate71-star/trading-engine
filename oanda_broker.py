"""
OANDA Broker - Live trading on OANDA demo/practice accounts.
Uses OANDA REST API v20 for order placement and position management.
"""
import requests
from datetime import datetime
from typing import Optional, Dict
from executor import BrokerAPI, OrderResult


class OandaBroker(BrokerAPI):
    """
    OANDA broker for live trading on demo/practice accounts.
    
    Supports:
    - Market orders
    - Limit orders
    - Stop loss / Take profit
    - Position management
    """
    
    def __init__(
        self,
        account_id: str,
        api_token: str,
        practice: bool = True
    ):
        super().__init__(api_key=api_token, testnet=practice)
        self.account_id = account_id
        self.api_token = api_token
        
        # Practice vs Live endpoints
        if practice:
            self.api_url = "https://api-fxpractice.oanda.com"
        else:
            self.api_url = "https://api-fxtrade.oanda.com"
        
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
    
    def connect(self) -> bool:
        """Test connection to OANDA API."""
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                account = data.get("account", {})
                balance = account.get("balance", "N/A")
                print(f"[OANDA] Connected to account {self.account_id}")
                print(f"[OANDA] Balance: {balance}")
                self.connected = True
                return True
            else:
                print(f"[OANDA] Connection failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"[OANDA] Connection error: {e}")
            return False
    
    def _convert_symbol(self, symbol: str) -> str:
        """Convert symbol format (EURUSD -> EUR_USD)."""
        if "_" in symbol:
            return symbol
        # Common forex pairs
        if len(symbol) == 6:
            return f"{symbol[:3]}_{symbol[3:]}"
        # Metals like XAUUSD
        if symbol.startswith("XAU") or symbol.startswith("XAG"):
            return f"{symbol[:3]}_{symbol[3:]}"
        return symbol

    def _get_price_precision(self, symbol: str) -> int:
        """Get the decimal precision for an instrument's price."""
        # OANDA price precisions: forex=5, metals=3, indices=2
        if symbol.startswith("XAU") or symbol.startswith("XAG"):
            return 3  # Metals have 3 decimal places
        if symbol.startswith("US500") or symbol.startswith("US30") or symbol.startswith("US100"):
            return 2  # Indices have 2 decimal places
        if symbol.startswith("BTC"):
            return 1  # Crypto has 1 decimal place
        return 5  # Forex has 5 decimal places

    def _round_price(self, price: float, symbol: str) -> float:
        """Round price to OANDA's required precision."""
        precision = self._get_price_precision(symbol)
        return round(price, precision)
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss: float = None,
        take_profit: float = None
    ) -> OrderResult:
        """
        Place a market order on OANDA.
        
        Args:
            symbol: Trading pair (e.g., EURUSD or EUR_USD)
            side: BUY or SELL
            quantity: Number of units (positive for buy, will be negated for sell)
            stop_loss: Optional stop loss price
            take_profit: Optional take profit price
        """
        instrument = self._convert_symbol(symbol)
        
        # OANDA uses positive units for buy, negative for sell
        units = int(quantity) if side.upper() == "BUY" else -int(quantity)

        # Round SL/TP to proper precision for this instrument
        if stop_loss:
            stop_loss = self._round_price(stop_loss, symbol)
        if take_profit:
            take_profit = self._round_price(take_profit, symbol)

        order_data = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "IOC",  # IOC works for all instruments including metals
                "positionFill": "DEFAULT"
            }
        }

        # Add stop loss if provided
        if stop_loss:
            precision = self._get_price_precision(symbol)
            order_data["order"]["stopLossOnFill"] = {
                "price": f"{stop_loss:.{precision}f}"
            }

        # Add take profit if provided
        if take_profit:
            precision = self._get_price_precision(symbol)
            order_data["order"]["takeProfitOnFill"] = {
                "price": f"{take_profit:.{precision}f}"
            }
        
        try:
            response = requests.post(
                f"{self.api_url}/v3/accounts/{self.account_id}/orders",
                headers=self.headers,
                json=order_data,
                timeout=10
            )
            
            if response.status_code == 201:
                data = response.json()
                
                # Check if order was filled
                if "orderFillTransaction" in data:
                    fill = data["orderFillTransaction"]
                    order_id = fill.get("id")
                    filled_price = float(fill.get("price", 0))
                    filled_units = abs(int(float(fill.get("units", 0))))  # Handle decimal units from OANDA
                    
                    # Calculate fees (OANDA uses spread, no explicit commission)
                    fees = 0.0
                    
                    print(f"[OANDA] {side} {filled_units} {instrument} @ {filled_price}")
                    
                    return OrderResult(
                        success=True,
                        order_id=order_id,
                        filled_price=filled_price,
                        filled_quantity=filled_units,
                        fees=fees,
                        timestamp=datetime.utcnow()
                    )
                else:
                    # Order created but not filled yet
                    order_create = data.get("orderCreateTransaction", {})
                    return OrderResult(
                        success=False,
                        error=f"Order created but not filled: {order_create.get('id')}"
                    )
            else:
                error_msg = response.json().get("errorMessage", response.text)
                print(f"[OANDA] Order failed: {error_msg}")
                return OrderResult(
                    success=False,
                    error=error_msg
                )
                
        except Exception as e:
            print(f"[OANDA] Order error: {e}")
            return OrderResult(
                success=False,
                error=str(e)
            )
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_loss: float = None,
        take_profit: float = None
    ) -> OrderResult:
        """Place a limit order on OANDA."""
        instrument = self._convert_symbol(symbol)
        units = int(quantity) if side.upper() == "BUY" else -int(quantity)

        # Round SL/TP to proper precision for this instrument
        if stop_loss:
            stop_loss = self._round_price(stop_loss, symbol)
        if take_profit:
            take_profit = self._round_price(take_profit, symbol)

        order_data = {
            "order": {
                "type": "LIMIT",
                "instrument": instrument,
                "units": str(units),
                "price": f"{price:.5f}",
                "timeInForce": "GTC"  # Good Till Cancelled
            }
        }

        if stop_loss:
            precision = self._get_price_precision(symbol)
            order_data["order"]["stopLossOnFill"] = {"price": f"{stop_loss:.{precision}f}"}
        if take_profit:
            precision = self._get_price_precision(symbol)
            order_data["order"]["takeProfitOnFill"] = {"price": f"{take_profit:.{precision}f}"}
        
        try:
            response = requests.post(
                f"{self.api_url}/v3/accounts/{self.account_id}/orders",
                headers=self.headers,
                json=order_data,
                timeout=10
            )
            
            if response.status_code == 201:
                data = response.json()
                order_create = data.get("orderCreateTransaction", {})
                order_id = order_create.get("id")
                
                print(f"[OANDA] Limit order placed: {side} {quantity} {instrument} @ {price}")
                
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    filled_price=0,  # Not filled yet
                    filled_quantity=0,
                    timestamp=datetime.utcnow()
                )
            else:
                error_msg = response.json().get("errorMessage", response.text)
                return OrderResult(success=False, error=error_msg)
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    def close_position(self, symbol: str, units: int = None) -> OrderResult:
        """
        Close a position on OANDA.
        
        Args:
            symbol: Trading pair
            units: Number of units to close (None = close all)
        """
        instrument = self._convert_symbol(symbol)
        
        close_data = {}
        if units:
            close_data["longUnits"] = str(abs(units))
        else:
            close_data["longUnits"] = "ALL"
            close_data["shortUnits"] = "ALL"
        
        try:
            response = requests.put(
                f"{self.api_url}/v3/accounts/{self.account_id}/positions/{instrument}/close",
                headers=self.headers,
                json=close_data,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Get fill info
                long_fill = data.get("longOrderFillTransaction")
                short_fill = data.get("shortOrderFillTransaction")
                fill = long_fill or short_fill
                
                if fill:
                    filled_price = float(fill.get("price", 0))
                    filled_units = abs(int(float(fill.get("units", 0))))  # Handle decimal units from OANDA
                    pnl = float(fill.get("pl", 0))
                    
                    print(f"[OANDA] Closed {instrument}: {filled_units} units @ {filled_price}, P&L: {pnl}")
                    
                    return OrderResult(
                        success=True,
                        order_id=fill.get("id"),
                        filled_price=filled_price,
                        filled_quantity=filled_units,
                        fees=0,
                        timestamp=datetime.utcnow()
                    )
                
                return OrderResult(success=True, timestamp=datetime.utcnow())
            else:
                error_msg = response.json().get("errorMessage", response.text)
                return OrderResult(success=False, error=error_msg)
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a pending order."""
        try:
            response = requests.put(
                f"{self.api_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel",
                headers=self.headers,
                timeout=10
            )
            return response.status_code == 200
        except:
            return False
    
    def get_position(self, symbol: str) -> Optional[dict]:
        """Get current position for a symbol."""
        instrument = self._convert_symbol(symbol)
        
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}/positions/{instrument}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                position = data.get("position", {})
                
                long_units = int(position.get("long", {}).get("units", 0))
                short_units = abs(int(position.get("short", {}).get("units", 0)))
                
                if long_units > 0:
                    return {
                        "symbol": symbol,
                        "side": "LONG",
                        "units": long_units,
                        "avg_price": float(position.get("long", {}).get("averagePrice", 0)),
                        "unrealized_pnl": float(position.get("long", {}).get("unrealizedPL", 0))
                    }
                elif short_units > 0:
                    return {
                        "symbol": symbol,
                        "side": "SHORT",
                        "units": short_units,
                        "avg_price": float(position.get("short", {}).get("averagePrice", 0)),
                        "unrealized_pnl": float(position.get("short", {}).get("unrealizedPL", 0))
                    }
                
            return None
        except:
            return None
    
    def get_all_positions(self) -> Dict[str, dict]:
        """Get all open positions."""
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}/openPositions",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                positions = {}
                
                for pos in data.get("positions", []):
                    instrument = pos.get("instrument")
                    symbol = instrument.replace("_", "")
                    
                    long_units = int(float(pos.get("long", {}).get("units", 0)))
                    short_units = abs(int(float(pos.get("short", {}).get("units", 0))))
                    
                    if long_units > 0:
                        positions[symbol] = {
                            "side": "LONG",
                            "units": long_units,
                            "avg_price": float(pos.get("long", {}).get("averagePrice", 0)),
                            "unrealized_pnl": float(pos.get("long", {}).get("unrealizedPL", 0))
                        }
                    elif short_units > 0:
                        positions[symbol] = {
                            "side": "SHORT",
                            "units": short_units,
                            "avg_price": float(pos.get("short", {}).get("averagePrice", 0)),
                            "unrealized_pnl": float(pos.get("short", {}).get("unrealizedPL", 0))
                        }
                
                return positions
            return {}
        except:
            return {}
    
    def get_balance(self) -> dict:
        """Get account balance and equity."""
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                account = data.get("account", {})
                
                return {
                    "balance": float(account.get("balance", 0)),
                    "nav": float(account.get("NAV", 0)),
                    "unrealized_pnl": float(account.get("unrealizedPL", 0)),
                    "margin_used": float(account.get("marginUsed", 0)),
                    "margin_available": float(account.get("marginAvailable", 0)),
                    "open_trade_count": int(account.get("openTradeCount", 0)),
                    "currency": account.get("currency", "USD")
                }
            return {}
        except:
            return {}
    
    def get_instrument_pricing(self, symbol: str) -> Optional[dict]:
        """Get current pricing info for an instrument."""
        instrument = self._convert_symbol(symbol)
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}/pricing?instruments={instrument}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                prices = data.get("prices", [])
                if prices:
                    p = prices[0]
                    return {
                        "symbol": symbol,
                        "bid": float(p.get("bids", [{}])[0].get("price", 0) or 0),
                        "ask": float(p.get("asks", [{}])[0].get("price", 0) or 0),
                        "mid": (float(p.get("closeoutBid", 0) or 0) + float(p.get("closeoutAsk", 0) or 0)) / 2,
                        "tradeable": p.get("tradeable", False),
                        "units_available": p.get("unitsAvailable", {}).get("default", 0)
                    }
            return None
        except Exception as e:
            print(f"[OANDA] Failed to get pricing for {symbol}: {e}")
            return None

    def get_instrument_candles(self, symbol: str, timeframe: str = "D1", count: int = 2) -> Optional[list]:
        """Get historical candles for an instrument to calculate 24h change."""
        instrument = self._convert_symbol(symbol)
        granularity_map = {"H1": "H1", "H4": "H4", "D1": "D1", "M5": "M5"}
        granularity = granularity_map.get(timeframe, "D1")

        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}/candles",
                headers=self.headers,
                params={
                    "instrument": instrument,
                    "granularity": granularity,
                    "count": count
                },
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                candles = []
                for c in data.get("candles", []):
                    candles.append({
                        "time": c.get("time"),
                        "open": float(c.get("o", 0)),
                        "high": float(c.get("h", 0)),
                        "low": float(c.get("l", 0)),
                        "close": float(c.get("c", 0)),
                        "volume": int(c.get("volume", 0))
                    })
                return candles
            return None
        except Exception as e:
            print(f"[OANDA] Failed to get candles for {symbol}: {e}")
            return None

    def get_open_trades(self) -> list:
        """Get all open trades with details."""
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}/openTrades",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                trades = []
                
                for trade in data.get("trades", []):
                    trades.append({
                        "id": trade.get("id"),
                        "instrument": trade.get("instrument"),
                        "units": int(float(trade.get("currentUnits", 0))),  # Handle decimal units from OANDA
                        "price": float(trade.get("price", 0)),
                        "unrealized_pnl": float(trade.get("unrealizedPL", 0)),
                        "open_time": trade.get("openTime"),
                        "stop_loss": trade.get("stopLossOrder", {}).get("price"),
                        "take_profit": trade.get("takeProfitOrder", {}).get("price")
                    })
                
                return trades
            return []
        except:
            return []
    
    def close_trade(self, trade_id: str, units: int = None) -> OrderResult:
        """Close a specific trade by ID."""
        close_data = {}
        if units:
            close_data["units"] = str(abs(units))
        else:
            close_data["units"] = "ALL"
        
        try:
            response = requests.put(
                f"{self.api_url}/v3/accounts/{self.account_id}/trades/{trade_id}/close",
                headers=self.headers,
                json=close_data,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                fill = data.get("orderFillTransaction", {})
                
                filled_price = float(fill.get("price", 0))
                pnl = float(fill.get("pl", 0))
                
                print(f"[OANDA] Closed trade {trade_id} @ {filled_price}, P&L: {pnl}")

                return OrderResult(
                    success=True,
                    order_id=fill.get("id"),
                    filled_price=filled_price,
                    timestamp=datetime.utcnow()
                )
            else:
                error_msg = response.json().get("errorMessage", response.text)
                return OrderResult(success=False, error=error_msg)

        except Exception as e:
            return OrderResult(success=False, error=str(e))

    def modify_trade(self, trade_id: str, stop_loss: float = None, take_profit: float = None) -> OrderResult:
        """
        Modify stop loss and/or take profit on an open trade via OANDA's trade modify endpoint.
        """
        modify_data = {}

        if stop_loss is not None:
            precision = self._get_price_precision_for_instrument(trade_id)
            modify_data["stopLoss"] = {"price": f"{stop_loss:.{precision}f}"}

        if take_profit is not None:
            precision = self._get_price_precision_for_instrument(trade_id)
            modify_data["takeProfit"] = {"price": f"{take_profit:.{precision}f}"}

        if not modify_data:
            return OrderResult(success=False, error="No changes specified")

        try:
            response = requests.put(
                f"{self.api_url}/v3/accounts/{self.account_id}/trades/{trade_id}/modify",
                headers=self.headers,
                json=modify_data,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                trade = data.get("trade", {})
                print(f"[OANDA] Modified trade {trade_id}: SL={stop_loss}, TP={take_profit}")
                return OrderResult(
                    success=True,
                    order_id=trade.get("id"),
                    filled_price=float(trade.get("price", 0)),
                    timestamp=datetime.utcnow()
                )
            else:
                error_msg = response.json().get("errorMessage", response.text)
                print(f"[OANDA] Failed to modify trade {trade_id}: {error_msg}")
                return OrderResult(success=False, error=error_msg)

        except Exception as e:
            print(f"[OANDA] Exception modifying trade {trade_id}: {e}")
            return OrderResult(success=False, error=str(e))

    def _get_price_precision_for_instrument(self, trade_id: str) -> int:
        """Get price precision for instrument by trade ID lookup."""
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}/trades/{trade_id}",
                headers=self.headers, timeout=10
            )
            if response.status_code == 200:
                instrument = response.json().get("trade", {}).get("instrument", "")
                return self._get_price_precision(instrument)
        except:
            pass
        return 5  # Default for forex
