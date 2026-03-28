import pandas as pd
import time
from connections import redis_client

def replay_csv(file):
    df = pd.read_csv(file)

    for _, row in df.iterrows():
        price = row["price"]

        print(f"Replay Tick: {price}")

        redis_client.set("latest_price", price)

        time.sleep(0.1)  # speed control


if __name__ == "__main__":
    replay_csv("data.csv")
