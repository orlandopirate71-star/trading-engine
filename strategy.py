class SimpleStrategy:
    def __init__(self):
        self.last_price = None

    def on_tick(self, price):
        signal = None

        if self.last_price is not None:
            if price > self.last_price:
                signal = "BUY"
            elif price < self.last_price:
                signal = "SELL"

        self.last_price = price
        return signal
