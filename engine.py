import time
from strategy import SimpleStrategy
from connections import redis_client, get_db_connection

strategy = SimpleStrategy()
last_price = None

def store_trade(signal, price):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO test (name) VALUES (%s)",
        (f"{signal} at {price}",)
    )

    conn.commit()
    cur.close()
    conn.close()

while True:
    price = redis_client.get("latest_price")

    if price:
        price = float(price)

        # ✅ Only act if price changed
        if price != last_price:
            print(f"Tick: {price}")

            signal = strategy.on_tick(price)

            if signal:
                print(f"Signal: {signal}")
                store_trade(signal, price)

            last_price = price

    time.sleep(0.1)