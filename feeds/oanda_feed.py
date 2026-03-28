"""
OANDA feed - Best for Forex.
Free practice account available at: https://www.oanda.com/
Requires account ID and API token.
"""
import json
import requests
from typing import List, Callable
from datetime import datetime
import time

from .base_feed import BaseFeed, Tick


class OandaFeed(BaseFeed):
    """
    OANDA streaming API for forex.
    Best quality forex data, free with practice account.
    
    Symbols format: EUR_USD, GBP_USD, USD_JPY, etc.
    """
    
    name = "OANDA"
    
    def __init__(
        self, 
        symbols: List[str], 
        account_id: str,
        api_token: str,
        practice: bool = True,
        on_tick: Callable[[Tick], None] = None
    ):
        super().__init__(symbols, on_tick)
        self.account_id = account_id
        self.api_token = api_token
        
        # Practice vs Live endpoints
        if practice:
            self.stream_url = "https://stream-fxpractice.oanda.com"
            self.api_url = "https://api-fxpractice.oanda.com"
        else:
            self.stream_url = "https://stream-fxtrade.oanda.com"
            self.api_url = "https://api-fxtrade.oanda.com"
    
    def connect(self) -> bool:
        # Test connection
        try:
            response = requests.get(
                f"{self.api_url}/v3/accounts/{self.account_id}",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=10
            )
            return response.status_code == 200
        except:
            return False
    
    def disconnect(self):
        self.running = False
    
    def _run(self):
        """Stream prices from OANDA."""
        instruments = ",".join(self.symbols)
        url = f"{self.stream_url}/v3/accounts/{self.account_id}/pricing/stream"
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        params = {"instruments": instruments}
        
        while self.running:
            try:
                print(f"[{self.name}] Connecting to stream...")
                
                with requests.get(url, headers=headers, params=params, stream=True, timeout=30) as response:
                    if response.status_code != 200:
                        print(f"[{self.name}] Error: {response.status_code}")
                        time.sleep(5)
                        continue
                    
                    print(f"[{self.name}] Streaming {len(self.symbols)} forex pairs")
                    
                    for line in response.iter_lines():
                        if not self.running:
                            break
                        
                        if line:
                            try:
                                data = json.loads(line.decode('utf-8'))
                                
                                if data.get("type") == "PRICE":
                                    symbol = data.get("instrument", "")
                                    bids = data.get("bids", [{}])
                                    asks = data.get("asks", [{}])
                                    
                                    bid = float(bids[0].get("price", 0)) if bids else 0
                                    ask = float(asks[0].get("price", 0)) if asks else 0
                                    price = (bid + ask) / 2
                                    
                                    tick = Tick(
                                        symbol=symbol.replace("_", ""),  # EUR_USD -> EURUSD
                                        price=price,
                                        bid=bid,
                                        ask=ask,
                                        source=self.name
                                    )
                                    self.emit_tick(tick)
                                    
                            except json.JSONDecodeError:
                                continue
                                
            except requests.exceptions.RequestException as e:
                print(f"[{self.name}] Connection error: {e}")
                if self.running:
                    time.sleep(5)
            except Exception as e:
                print(f"[{self.name}] Error: {e}")
                if self.running:
                    time.sleep(5)
