import time
import json
import os
import schema_pb2
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zo_sdk import ZoClient, session_sign


# ==============================
# ====== 稳健非等距网格机器人 ====
# ==============================
class RobustAsymmetricBot:
    def __init__(self, config_path="session_cache.json"):
        # 1. 默认加载 session_cache.json
        self.load_config(config_path)
        self.client = ZoClient()

        # 2. 策略参数
        self.market_id = 0
        self.num_grids_per_side = 20
        self.order_size = 0.005
        self.refresh_interval = 5
        self.base_step = 0.0004
        self.step_multiplier = 1.015
        self.rebalance_threshold = 0.008

        self.center_price = None
        self.target_prices = []

    def load_config(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"❌ 找不到配置文件: {path}")
        with open(path, "r") as f:
            data = json.load(f)

        # 兼容 list 或 bytes 格式的存储
        self.session_id = data["session_id"]
        self.session_key = Ed25519PrivateKey.from_private_bytes(bytes(data["session_key"]))
        self.user_pubkey = bytes(data["user_pubkey"])
        print(f"✅ 成功加载会话: {path}")

    def get_mid_price(self):
        stats = self.client.get_market_stats(self.market_id)
        return float(stats["perpStats"]["mark_price"])

    def round_to_tick(self, price, decimals):
        factor = 10 ** decimals
        return round(price * factor) / factor

    def initialize_grid(self):
        mid_price = self.get_mid_price()
        self.center_price = mid_price
        self.target_prices = []

        markets = self.client.get_markets()
        price_dec = markets[self.market_id]["price_decimals"]

        for direction in [-1, 1]:
            offset = 0
            step = self.base_step
            for _ in range(self.num_grids_per_side):
                offset += step
                p = self.round_to_tick(mid_price * (1 + (direction * offset)), price_dec)
                self.target_prices.append(p)
                step *= self.step_multiplier

        print(f"🔄 网格初始化! 中心价: ${self.center_price:,.2f}")
        print(f"📊 范围: ${min(self.target_prices):,.2f} - ${max(self.target_prices):,.2f}")

    def sync_grid(self):
        curr_price = self.get_mid_price()

        if abs(curr_price - self.center_price) / self.center_price > self.rebalance_threshold:
            print(f"⚠️ 价格偏离，重置中...")
            self.cancel_all_orders()
            self.initialize_grid()
            return

        orders = self.client.get_open_orders(self.user_pubkey, market_id=self.market_id)
        existing_prices = [round(float(o['price']), 6) for o in orders]

        for price in self.target_prices:
            if price not in existing_prices:
                side = schema_pb2.Side.BID if price < curr_price else schema_pb2.Side.ASK
                if (side == schema_pb2.Side.BID and price > curr_price) or \
                        (side == schema_pb2.Side.ASK and price < curr_price):
                    continue

                try:
                    self.client.place_limit_order(
                        session_id=self.session_id,
                        session_key=self.session_key,
                        session_sign=session_sign,
                        market_id=self.market_id,
                        side=side,
                        price=price,
                        size=self.order_size,
                    )
                    time.sleep(0.2)
                except Exception as e:
                    print(f"❌ 下单失败: {e}")

    def cancel_all_orders(self):
        orders = self.client.get_open_orders(self.user_pubkey, market_id=self.market_id)
        for o in orders:
            try:
                self.client.cancel_order(self.session_id, self.session_key, session_sign, o['orderId'])
            except:
                pass

    def run(self):
        print(f"🚀 稳健机器人运行中 (Account: {self.user_pubkey.hex()[:8]})")
        self.initialize_grid()
        while True:
            try:
                self.sync_grid()
            except Exception as e:
                print(f"⚠️ 异常: {e}")
            time.sleep(self.refresh_interval)


# ==============================
# ====== 简化后的启动入口 ========
# ==============================
if __name__ == "__main__":
    # 直接硬编码指向 session_cache.json
    try:
        bot = RobustAsymmetricBot("session_cache.json")
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 机器人已安全停止")
    except Exception as e:
        print(f"❌ 启动失败: {e}")