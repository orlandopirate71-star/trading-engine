"""
Screenshot capture service for trade documentation.
Captures charts at trade open and close for historical records.
Supports TradingView, OANDA, and full screen capture modes.
"""
import os
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
import threading

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[SCREENSHOT] Selenium not available - screenshots disabled")

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


# TradingView exchange mapping for OANDA symbols
TRADINGVIEW_EXCHANGES = {
    "XAUUSD": "OANDA",
    "XAGUSD": "OANDA",
    "EURUSD": "OANDA",
    "GBPUSD": "OANDA",
    "USDJPY": "OANDA",
    "USDCHF": "OANDA",
    "AUDUSD": "OANDA",
    "USDCAD": "OANDA",
    "NZDUSD": "OANDA",
    "EURGBP": "OANDA",
    "EURJPY": "OANDA",
    "GBPJPY": "OANDA",
    "BTCUSDT": "BINANCE",
    "ETHUSDT": "BINANCE",
    "SOLUSDT": "BINANCE",
    "default": "OANDA"
}

DEFAULT_TIMEFRAMES = ["M5", "M15", "H1", "H4"]


class ScreenshotService:
    def __init__(self, screenshots_dir: str = "screenshots"):
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(exist_ok=True)
        self.driver = None
        self.tradingview_url_template = "https://www.tradingview.com/widgetembed/?symbol={exchange}:{symbol}&interval={interval}&width=1920&height=1080"
        self.credentials_file = Path(__file__).parent / "screenshot_credentials.json"

    def _load_credentials(self) -> dict:
        if self.credentials_file.exists():
            try:
                with open(self.credentials_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _get_exchange(self, symbol: str) -> str:
        return TRADINGVIEW_EXCHANGES.get(symbol, TRADINGVIEW_EXCHANGES["default"])

    def _init_driver(self):
        if not SELENIUM_AVAILABLE:
            return False
        if self.driver:
            return True
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-gpu")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            self.driver = webdriver.Chrome(options=options)
            print("[SCREENSHOT] Chrome driver initialized")
            return True
        except Exception as e:
            print(f"[SCREENSHOT] Failed to initialize Chrome driver: {e}")
            return False

    def capture_tradingview(
        self,
        symbol: str,
        trade_id: int,
        event_type: str = "entry",
        exchange: str = None,
        timeframes: List[str] = None
    ) -> List[Dict[str, str]]:
        if not SELENIUM_AVAILABLE:
            return [{"timeframe": "placeholder", "path": self._capture_placeholder(symbol, trade_id, event_type)}]

        if timeframes is None:
            timeframes = DEFAULT_TIMEFRAMES

        if not self._init_driver():
            return [{"timeframe": "error", "path": self._capture_placeholder(symbol, trade_id, event_type)}]

        results = []
        exchange = exchange or self._get_exchange(symbol)

        for tf in timeframes:
            try:
                url = self.tradingview_url_template.format(exchange=exchange, symbol=symbol, interval=tf)
                self.driver.get(url)
                time.sleep(4)

                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                filename = f"trade_{trade_id}_{event_type}_{tf}_{timestamp}.png"
                filepath = self.screenshots_dir / filename
                self.driver.save_screenshot(str(filepath))

                print(f"[SCREENSHOT] Captured {event_type} {tf}: {filepath}")
                results.append({"timeframe": tf, "path": str(filepath)})
            except Exception as e:
                print(f"[SCREENSHOT] Failed to capture {tf}: {e}")

        return results if results else [{"timeframe": "error", "path": None}]

    def capture_full_screen(self, trade_id: int, event_type: str = "entry", region: dict = None) -> Optional[str]:
        if not MSS_AVAILABLE:
            return None
        try:
            with mss.mss() as sct:
                monitor = region or sct.monitors[1]
                screenshot = sct.grab(monitor)
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                filename = f"trade_{trade_id}_{event_type}_screen_{timestamp}.png"
                filepath = self.screenshots_dir / filename
                mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(filepath))
                print(f"[SCREENSHOT] Screen capture saved: {filepath}")
                return str(filepath)
        except Exception as e:
            print(f"[SCREENSHOT] Screen capture failed: {e}")
            return None

    def capture_all(self, symbol: str, trade_id: int, event_type: str = "entry") -> Dict[str, List[Dict]]:
        results = {"tradingview": [], "screen": None}
        tv_results = self.capture_tradingview(symbol=symbol, trade_id=trade_id, event_type=event_type)
        results["tradingview"] = tv_results
        screen_path = self.capture_full_screen(trade_id, event_type)
        if screen_path:
            results["screen"] = screen_path
        return results

    def _capture_placeholder(self, symbol: str, trade_id: int, event_type: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"trade_{trade_id}_{event_type}_{timestamp}.txt"
        filepath = self.screenshots_dir / filename
        content = f"""Screenshot Placeholder
======================
Trade ID: {trade_id}
Symbol: {symbol}
Event: {event_type}
Timestamp: {datetime.now(timezone.utc).isoformat()}
"""
        filepath.write_text(content)
        return str(filepath)

    def cleanup(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def get_screenshots_for_trade(self, trade_id: int) -> dict:
        entry_shots = list(self.screenshots_dir.glob(f"trade_{trade_id}_entry_*"))
        exit_shots = list(self.screenshots_dir.glob(f"trade_{trade_id}_exit_*"))
        return {"entry": [str(p) for p in entry_shots], "exit": [str(p) for p in exit_shots]}


_screenshot_service = None


def get_screenshot_service(screenshots_dir: str = "screenshots") -> ScreenshotService:
    global _screenshot_service
    if _screenshot_service is None:
        _screenshot_service = ScreenshotService(screenshots_dir)
    return _screenshot_service


if __name__ == "__main__":
    service = get_screenshot_service()
    result = service.capture_tradingview("XAUUSD", 999, "test", ["M5"])
    print(result)
