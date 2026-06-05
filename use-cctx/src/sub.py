"""
使用 ccxt 下单 demo
支持：限价单、市价单、取消订单、查询订单状态

环境变量：
  export EXCHANGE_ID=binance
  export API_KEY=your_api_key
  export API_SECRET=your_api_secret
  export API_PASSPHRASE=your_passphrase   # 仅部分交易所需要，如 OKX

注意：默认使用沙盒模式（sandbox=True），真实交易请将 USE_SANDBOX 设为 false。
"""

import os
import time

import truststore
truststore.inject_into_ssl()

import ccxt

# ── 沙盒开关 ──────────────────────────────────────────────────
USE_SANDBOX = os.environ.get("USE_SANDBOX", "true").lower() != "false"


def get_exchange(exchange_id: str | None = None) -> ccxt.Exchange:
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
    exchange = exchange_class(config)
    if USE_SANDBOX and exchange.has.get("sandbox"):
        exchange.set_sandbox_mode(True)
        print("[沙盒模式] 订单不会真实成交")
    return exchange


# ── 下单函数 ──────────────────────────────────────────────────

def place_limit_order(
    exchange: ccxt.Exchange,
    symbol: str,
    side: str,          # "buy" | "sell"
    amount: float,
    price: float,
) -> dict:
    """提交限价单，返回交易所原始响应。"""
    order = exchange.create_order(
        symbol=symbol,
        type="limit",
        side=side,
        amount=amount,
        price=price,
    )
    return order


def place_market_order(
    exchange: ccxt.Exchange,
    symbol: str,
    side: str,
    amount: float,
) -> dict:
    """提交市价单，返回交易所原始响应。"""
    order = exchange.create_order(
        symbol=symbol,
        type="market",
        side=side,
        amount=amount,
    )
    return order


def cancel_order(exchange: ccxt.Exchange, order_id: str, symbol: str) -> dict:
    """撤销指定订单。"""
    return exchange.cancel_order(order_id, symbol)


def fetch_order(exchange: ccxt.Exchange, order_id: str, symbol: str) -> dict:
    """查询订单当前状态。"""
    return exchange.fetch_order(order_id, symbol)


def fetch_open_orders(exchange: ccxt.Exchange, symbol: str) -> list[dict]:
    """查询所有未成交订单。"""
    return exchange.fetch_open_orders(symbol)


# ── 格式化输出 ────────────────────────────────────────────────

def print_order(order: dict) -> None:
    fields = ["id", "symbol", "type", "side", "amount", "price", "filled", "status", "datetime"]
    width = max(len(f) for f in fields)
    for f in fields:
        print(f"  {f:{width}s}: {order.get(f)}")


# ── 主流程 ────────────────────────────────────────────────────

def main():
    exchange = get_exchange()
    symbol = "BTC/USDT"

    # 1. 当前盘口价，用于设定合理限价
    ticker = exchange.fetch_ticker(symbol)
    last_price = ticker["last"]
    print(f"\n{symbol} 当前价格: {last_price:,.2f} USDT")

    # ── 示例 1：限价买单（价格低于市价 5%，不会立即成交）──
    limit_price = round(last_price * 0.95, 2)
    amount = 0.001  # BTC

    print(f"\n[1] 提交限价买单: {amount} BTC @ {limit_price:,.2f} USDT")
    limit_order = place_limit_order(exchange, symbol, "buy", amount, limit_price)
    print("  订单详情:")
    print_order(limit_order)

    # 等待一秒后查询订单状态
    time.sleep(1)
    order_id = limit_order["id"]
    fetched = fetch_order(exchange, order_id, symbol)
    print(f"\n  查询订单状态: {fetched['status']}")

    # 撤销限价单
    print(f"\n[2] 撤销限价单 id={order_id}")
    cancelled = cancel_order(exchange, order_id, symbol)
    print(f"  撤销结果: {cancelled.get('status', cancelled)}")

    # ── 示例 2：查询未成交订单 ──
    print(f"\n[3] 查询 {symbol} 当前未成交订单")
    open_orders = fetch_open_orders(exchange, symbol)
    if open_orders:
        for o in open_orders:
            print_order(o)
            print()
    else:
        print("  无未成交订单")

    # ── 示例 3：市价买单（谨慎：会立即成交）──
    # 默认注释掉，需要时手动启用
    # print(f"\n[4] 提交市价买单: {amount} BTC")
    # market_order = place_market_order(exchange, symbol, "buy", amount)
    # print("  订单详情:")
    # print_order(market_order)


if __name__ == "__main__":
    main()
