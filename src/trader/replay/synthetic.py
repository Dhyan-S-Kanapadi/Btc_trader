"""Deterministic clearly synthetic candle generation for replay tests only."""

from datetime import datetime
from decimal import Decimal
from random import Random

from trader.data.binance import interval_delta
from trader.models import Candle


def generate_candles(seed: int, n: int, start_time: datetime, interval: str) -> list[Candle]:
    """Generate valid SYNTH-BTC toy candles with deterministic trend, range, and volume bursts."""

    if n <= 0:
        raise ValueError("n must be positive")
    step = interval_delta(interval)
    random = Random(seed)
    price = Decimal("100")
    candles: list[Candle] = []
    for index in range(n):
        phase = (index // 40) % 3
        drift = Decimal("0.8") if phase == 0 else Decimal("-0.4") if phase == 1 else Decimal("0")
        change = drift + Decimal(str(random.uniform(-1, 1)))
        open_price = price
        close = max(Decimal("1"), open_price + change)
        high = max(open_price, close) + Decimal(str(random.uniform(0, 1)))
        low = min(open_price, close) - Decimal(str(random.uniform(0, 1)))
        volume = Decimal(str(random.uniform(1, 5))) * (Decimal("5") if index % 37 == 0 else 1)
        candles.append(
            Candle(
                symbol="SYNTH-BTC",
                open_time=start_time + index * step,
                open=open_price,
                high=high,
                low=max(Decimal("0.01"), low),
                close=close,
                volume=volume,
            )
        )
        price = close
    return candles
