import json
import websocket
from connections import redis_client

REDIS_CHANNEL = "ticks"


def publish_tick(price):
    # Publish to Redis channel (event-driven)
    redis_client.publish(REDIS_CHANNEL, price)

    # Also store latest value (optional but useful)
    redis_client.set("latest_price", price)


def on_message(ws, message):
    try:
        data = json.loads(message)

        # Binance ticker price
        price = float(data["c"])

        print(f"[FEED] Price: {price}")

        publish_tick(price)

    except Exception as e:
        print("[FEED ERROR]", e)


def on_error(ws, error):
    print("[WEBSOCKET ERROR]", error)


def on_close(ws, close_status_code, close_msg):
    print("[WEBSOCKET CLOSED]", close_status_code, close_msg)


def on_open(ws):
    print("[FEED] Connected to Binance WebSocket")


def start_feed():
    url = "wss://stream.binance.com:9443/ws/btcusdt@ticker"

    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    ws.on_open = on_open

    # Auto-reconnect loop
    while True:
        try:
            ws.run_forever()
        except Exception as e:
            print("[RECONNECTING]", e)


if __name__ == "__main__":
    start_feed()