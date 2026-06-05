"""
使用 ccxt 查询加密货币市场行情
查询 BTC/USDT、ETH/USDT 等主要交易对的实时数据
"""

import truststore
# Inject macOS Keychain trust into Python's ssl module so urllib3/requests
# can verify certificates signed by proxies/VPNs trusted by the system.
truststore.inject_into_ssl()

import ccxt
import pandas as pd
from datetime import datetime, timezone


def get_exchange(exchange_id: str = "binance") -> ccxt.Exchange:
    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })


def fetch_ticker(exchange: ccxt.Exchange, symbol: str) -> dict:
    ticker = exchange.fetch_ticker(symbol)
    return {
        "symbol": ticker["symbol"],
        "last": ticker["last"],
        "bid": ticker["bid"],
        "ask": ticker["ask"],
        "high": ticker["high"],
        "low": ticker["low"],
        "volume": ticker["baseVolume"],
        "change_pct": ticker["percentage"],
        "timestamp": datetime.fromtimestamp(ticker["timestamp"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, timeframe: str = "1d", limit: int = 10) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime").drop(columns=["timestamp"])
    return df


def fetch_order_book(exchange: ccxt.Exchange, symbol: str, depth: int = 5) -> dict:
    ob = exchange.fetch_order_book(symbol, limit=depth)
    return {
        "symbol": symbol,
        "bids": ob["bids"][:depth],
        "asks": ob["asks"][:depth],
        "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def main():
    # binance
    exchange = get_exchange("toobit")
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]

    print("=" * 60)
    print("实时行情 (Binance)")
    print("=" * 60)
    for symbol in symbols:
        t = fetch_ticker(exchange, symbol)
        print(
            f"{t['symbol']:12s}  last={t['last']:>12,.2f}  "
            f"24h_chg={t['change_pct']:>+6.2f}%  "
            f"vol={t['volume']:>14,.2f}  "
            f"high={t['high']:>12,.2f}  low={t['low']:>12,.2f}"
        )

    print()
    print("=" * 60)
    print("BTC/USDT 近 10 日 K 线 (日线)")
    print("=" * 60)
    df = fetch_ohlcv(exchange, "BTC/USDT", timeframe="1d", limit=10)
    print(df.to_string())

    print()
    print("=" * 60)
    print("BTC/USDT 盘口 (前 5 档)")
    print("=" * 60)
    ob = fetch_order_book(exchange, "BTC/USDT", depth=5)
    print(f"时间: {ob['timestamp']}")
    print(f"{'卖出 (Ask)':>30}  {'买入 (Bid)':<30}")
    print("-" * 62)
    for ask, bid in zip(reversed(ob["asks"]), ob["bids"]):
        print(f"{ask[0]:>14,.2f} @ {ask[1]:>10,.4f}  |  {bid[0]:<14,.2f} @ {bid[1]:<10,.4f}")


if __name__ == "__main__":
    main()
