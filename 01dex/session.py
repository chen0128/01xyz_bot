import json
import time
import schema_pb2
from cryptography.hazmat.primitives.asymmetric import ed25519
from base58 import b58encode, b58decode
from zo_sdk import ZoClient, execute_action, user_sign

# ==============================
# 配置区
# ==============================
TARGET_KEY_FILE = "id.json"  # 指定读取的文件名
CACHE_FILE_NAME = "session_cache.json" # 指定生成的缓存名

def load_user_key_from_file(filename):
    """从指定文件加载私钥"""
    try:
        with open(filename, "r") as f:
            raw_data = json.load(f)
        # 统一取前 32 字节私钥
        return ed25519.Ed25519PrivateKey.from_private_bytes(bytes(raw_data)[:32])
    except FileNotFoundError:
        print(f"❌ 找不到文件: {filename}")
        return None

def run_create_session():
    client = ZoClient()

    # 1. 加载 key
    user_signing_key = load_user_key_from_file(TARGET_KEY_FILE)
    if not user_signing_key:
        return

    user_pubkey_bytes = user_signing_key.public_key().public_bytes_raw()
    print(f"🔑 正在为账户建立 Session: {b58encode(user_pubkey_bytes).decode()}")

    # 2. 生成临时 Session Key
    session_signing_key = ed25519.Ed25519PrivateKey.generate()
    session_pubkey_bytes = session_signing_key.public_key().public_bytes_raw()

    action = schema_pb2.Action()
    server_now = client.get_server_time()
    action.current_timestamp = server_now

    # 赋值
    cs = action.create_session
    cs.user_pubkey = user_pubkey_bytes
    cs.session_pubkey = session_pubkey_bytes
    cs.expiry_timestamp = server_now + (7 * 24 * 3600)

    print(f"🚀 发送指令到主网...")

    try:
        receipt = execute_action(action, user_signing_key, user_sign)

        if receipt.HasField("err"):
            # 针对你遇到的 USER_NOT_FOUND 进行友好提示
            error_msg = schema_pb2.Error.Name(receipt.err)
            print(f"❌ API 报错: {error_msg}")
            if error_msg == "USER_NOT_FOUND":
                print("💡 提示: 该地址尚未在 Zo 激活。请先前往官网 Deposit 任意金额。")
            return

        session_id = receipt.create_session_result.session_id

        # 3. 保存区分化的缓存数据
        cache_data = {
            "source_file": TARGET_KEY_FILE,
            "session_id": session_id,
            "session_key": list(session_signing_key.private_bytes_raw()),
            "user_pubkey": list(user_pubkey_bytes)
        }

        with open(CACHE_FILE_NAME, "w") as f:
            json.dump(cache_data, f)

        print(f"\n✅ 成功！Session ID: {session_id}")
        print(f"💾 缓存已保存至: {CACHE_FILE_NAME}")

    except Exception as e:
        print(f"❌ 运行异常: {e}")

if __name__ == "__main__":
    run_create_session()