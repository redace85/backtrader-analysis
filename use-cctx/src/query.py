"""
使用 ccxt 查询账户余额
需要在环境变量中设置 API Key / Secret（可选 passphrase）：
  export EXCHANGE_ID=binance
  export API_KEY=your_api_key
  export API_SECRET=your_api_secret
  export API_PASSPHRASE=your_passphrase   # 仅部分交易所需要，如 OKX
"""

import os

import truststore
truststore.inject_into_ssl()

import ccxt
import pandas as pd


def get_authenticated_exchange(exchange_id: str | None = None) -> ccxt.Exchange:
    eid = exchange_id or os.environ.get("EXCHANGE_ID", "binance")
    exchange_class = getattr(ccxt, eid)
    config = {
        "apiKey": os.environ.get("API_KEY", ""),
        "secret": os.environ.get("API_SECRET", ""),
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
    passphrase = os.environ.get("API_PASSPHRASE")
    if passphrase:
        config["password"] = passphrase
    return exchange_class(config)


def fetch_balance(exchange: ccxt.Exchange, hide_zero: bool = True) -> pd.DataFrame:
    """返回账户各币种余额（可用 + 冻结）。"""
    raw = exchange.fetch_balance()
    rows = []
    for currency, info in raw["total"].items():
        free = raw["free"].get(currency, 0) or 0
        used = raw["used"].get(currency, 0) or 0
        total = info or 0
        if hide_zero and total == 0:
            continue
        rows.append({"currency": currency, "free": free, "used": used, "total": total})
    df = pd.DataFrame(rows, columns=["currency", "free", "used", "total"])
    df = df.sort_values("total", ascending=False).reset_index(drop=True)
    return df


def main():
    exchange = get_authenticated_exchange()
    print(f"交易所: {exchange.id}  (账户类型: spot)")
    print("=" * 55)

    df = fetch_balance(exchange)
    if df.empty:
        print("账户余额为空（或所有资产余额均为 0）。")
    else:
        print(df.to_string(index=False, float_format=lambda x: f"{x:.8f}"))

    print("=" * 55)
    total_usdt = df.loc[df["currency"] == "USDT", "total"].sum()
    if total_usdt:
        print(f"USDT 余额: {total_usdt:.4f}")


if __name__ == "__main__":
    main()
