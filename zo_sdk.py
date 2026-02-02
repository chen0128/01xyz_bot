# ==============================
# 01Trade 网格交易脚本
# ==============================

print("="*50)
print("01Trade 网格交易脚本")
print("作者: 黑大王")
print("推特: https://x.com/Pengchenop")
print("内测邀请码: https://01.xyz/ref/heidawang")
print("说明: 脚本仅用于学习与模拟交易，不构成投资建议")
print("="*50)
input("按回车键继续运行脚本...")


import binascii
import requests
import asyncio
import websockets
import json
import time
from datetime import datetime
from base58 import b58encode
from google.protobuf.internal import encoder, decoder
import schema_pb2  # 本地 protobuf 文件


API_URL = "https://zo-mainnet.n1.xyz"


# ==============================
# Protobuf 辅助函数
# ==============================
def get_varint_bytes(value):
    return encoder._VarintBytes(value)


def read_varint(buffer, offset=0):
    return decoder._DecodeVarint32(buffer, offset)


def user_sign(key, msg: bytes) -> bytes:
    """User signing: sign hex-encoded message (CreateSession)"""
    payload = binascii.hexlify(msg)
    return key.sign(payload)


def session_sign(key, msg: bytes) -> bytes:
    """Session signing: sign raw bytes (PlaceOrder/CancelOrder)"""
    return key.sign(msg)


def execute_action(action, signing_key, sign_func):
    """
    Serialize, sign, and send an Action to the API.
    Returns parsed Receipt.
    """
    payload = action.SerializeToString()
    length_prefix = get_varint_bytes(len(payload))
    message = length_prefix + payload

    signature = sign_func(signing_key, message)

    resp = requests.post(
        f"{API_URL}/action",
        data=message + signature,
        headers={"Content-Type": "application/octet-stream"}
    )
    resp.raise_for_status()

    msg_len, pos = read_varint(resp.content, 0)
    receipt = schema_pb2.Receipt()
    receipt.ParseFromString(resp.content[pos:pos + msg_len])
    return receipt


# ==============================
# 核心客户端
# ==============================
class ZoClient:
    def __init__(self, api_url=API_URL):
        self.api_url = api_url

    # --------------------------
    # 基础请求
    # --------------------------
    def _get(self, path, params=None):
        url = f"{self.api_url}{path}"
        resp = requests.get(url, params=params)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")
        return resp.json()

    def get_server_time(self) -> int:
        return int(self._get("/timestamp"))

    # --------------------------
    # MARKET 模块
    # --------------------------
    def get_markets(self):
        data = self._get("/info")
        markets = {}
        for m in data["markets"]:
            markets[m["marketId"]] = {
                "symbol": m["symbol"],
                "price_decimals": m["priceDecimals"],
                "size_decimals": m["sizeDecimals"],
            }
        return markets

    def get_tokens(self):
        data = self._get("/info")
        return data["tokens"]

    def get_market_stats(self, market_id: int):
        return self._get(f"/market/{market_id}/stats")

    def get_orderbook(self, market_id: int, depth: int = 10):
        book = self._get("/orderbook", params={"marketId": market_id})

        print(f"\n{'BIDS':^25} | {'ASKS':^25}")
        print("-" * 53)

        for i in range(min(depth, max(len(book["bids"]), len(book["asks"])))):
            bid = book["bids"][i] if i < len(book["bids"]) else ["-", "-"]
            ask = book["asks"][i] if i < len(book["asks"]) else ["-", "-"]

            bid_str = f"{bid[1]:.4f} @ ${bid[0]:,.1f}" if bid[0] != "-" else ""
            ask_str = f"${ask[0]:,.1f} @ {ask[1]:.4f}" if ask[0] != "-" else ""

            print(f"{bid_str:>25} | {ask_str:<25}")

        return book

    def get_recent_trades(self, market_id: int, limit: int = 20):
        data = self._get("/trades", params={"marketId": market_id, "pageSize": limit})

        print(f"\nRecent Trades (Market {market_id}):")
        print(f"{'Time':^12} | {'Side':^4} | {'Price':^12} | {'Size':^10}")
        print("-" * 45)

        for trade in data["trades"]:
            t = datetime.fromtimestamp(trade["timestamp"] / 1000)
            side = "BUY" if trade["side"] == "bid" else "SELL"
            print(
                f"{t:%H:%M:%S} | {side:^4} | "
                f"${trade['price']:>10,.1f} | {trade['size']:>10.4f}"
            )

        return data["trades"]

    # --------------------------
    # ACCOUNT 模块
    # --------------------------
    def get_user_info(self, user_pubkey: bytes):
        pubkey_b58 = b58encode(user_pubkey).decode()
        return self._get(f"/user/{pubkey_b58}")

    def monitor_positions(self, user_pubkey: bytes, interval: int = 5):
        pubkey_b58 = b58encode(user_pubkey).decode()
        print("Monitoring positions... (Ctrl+C to stop)")

        try:
            while True:
                info = self._get(f"/user/{pubkey_b58}")
                print(f"\n{'='*50}")
                print(f"Time: {time.strftime('%H:%M:%S')}")

                for pos in info.get("positions", []):
                    if pos["size"] != 0:
                        print(
                            f"Market {pos['marketId']}: "
                            f"Size={pos['size']:+.4f} "
                            f"Entry=${pos['entryPrice']:,.2f} "
                            f"PnL=${pos['unrealizedPnl']:+,.2f}"
                        )

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")

    def get_available_margin(self, user_pubkey: bytes):
        info = self.get_user_info(user_pubkey)
        total_available = sum(
            b["available"] for b in info.get("balances", []) if b["tokenId"] == 1
        )
        unrealized_pnl = sum(p["unrealizedPnl"] for p in info.get("positions", []))
        return total_available + unrealized_pnl

    def get_open_orders(self, user_pubkey: bytes, market_id: int = None):
        info = self.get_user_info(user_pubkey)
        orders = info.get("orders", [])

        if market_id is not None:
            orders = [o for o in orders if o["marketId"] == market_id]

        for order in orders:
            side = "BUY" if order["side"] == "bid" else "SELL"
            print(f"Order {order['orderId']}: {side} {order['size']:.4f} @ ${order['price']:,.2f}")

        return orders

    # --------------------------
    # TRADING 模块
    # --------------------------
    def place_limit_order(self, session_id, session_key, session_sign, market_id, side, price, size):
        markets = self.get_markets()
        market = markets[market_id]

        price_raw = int(price * (10 ** market["price_decimals"]))
        size_raw = int(size * (10 ** market["size_decimals"]))

        action = schema_pb2.Action()
        action.current_timestamp = self.get_server_time()
        action.place_order.session_id = session_id
        action.place_order.market_id = market_id
        action.place_order.side = side
        action.place_order.fill_mode = schema_pb2.FillMode.LIMIT
        action.place_order.price = price_raw
        action.place_order.size = size_raw

        receipt = execute_action(action, session_key, session_sign)

        if receipt.HasField("err"):
            raise Exception(f"PlaceOrder failed: {schema_pb2.Error.Name(receipt.err)}")

        result = receipt.place_order_result
        if result.HasField("posted"):
            print(f"✅ Order posted! ID: {result.posted.order_id}")
            return result.posted.order_id

        if result.fills:
            print(f"✅ Order filled! {len(result.fills)} fills")
            return None

        return None

    def place_market_order(self, session_id, session_key, session_sign, market_id, side, size):
        markets = self.get_markets()
        market = markets[market_id]
        size_raw = int(size * (10 ** market["size_decimals"]))

        action = schema_pb2.Action()
        action.current_timestamp = self.get_server_time()
        action.place_order.session_id = session_id
        action.place_order.market_id = market_id
        action.place_order.side = side
        action.place_order.fill_mode = schema_pb2.FillMode.FILL_OR_KILL
        action.place_order.size = size_raw

        receipt = execute_action(action, session_key, session_sign)

        if receipt.HasField("err"):
            raise Exception(f"Market order error: {schema_pb2.Error.Name(receipt.err)}")

        print(f"✅ Market order executed! Fills: {len(receipt.place_order_result.fills)}")
        return receipt.place_order_result

    # --------------------------
    # ORDER CANCEL
    # --------------------------
    def cancel_order(self, session_id, session_key, session_sign, order_id):
        action = schema_pb2.Action()
        action.current_timestamp = self.get_server_time()
        action.cancel_order_by_id.session_id = session_id
        action.cancel_order_by_id.order_id = order_id

        receipt = execute_action(action, session_key, session_sign)

        if receipt.HasField("err"):
            raise Exception(f"Cancel failed: {schema_pb2.Error.Name(receipt.err)}")

        print(f"✅ Order {order_id} cancelled!")
        return receipt

    def cancel_order_by_client_id(self, session_id, session_key, session_sign, client_order_id, account_id=None):
        action = schema_pb2.Action()
        action.current_timestamp = self.get_server_time()
        action.cancel_order_by_client_id.session_id = session_id
        action.cancel_order_by_client_id.client_order_id = client_order_id

        if account_id is not None:
            action.cancel_order_by_client_id.sender_account_id = account_id

        receipt = execute_action(action, session_key, session_sign)

        if receipt.HasField("err"):
            raise Exception(f"Cancel failed: {schema_pb2.Error.Name(receipt.err)}")

        print(f"✅ Order with client_order_id {client_order_id} cancelled!")
        return receipt

    # --------------------------
    # WEBSOCKET 实时行情
    # --------------------------
    async def stream_candles(self, symbol: str, resolution: str = "1"):
        uri = f"wss://zo-mainnet.n1.xyz/ws/candle@{symbol}:{resolution}"

        async with websockets.connect(uri) as ws:
            print(f"Connected to {symbol} {resolution}m candles")

            async for message in ws:
                candle = json.loads(message)
                print(
                    f"O: {candle['o']:.1f} "
                    f"H: {candle['h']:.1f} "
                    f"L: {candle['l']:.1f} "
                    f"C: {candle['c']:.1f}"
                )
