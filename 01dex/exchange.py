import json
from base58 import b58decode

# 你的 Base58 格式私钥
base58_string = ""

try:
    # 解码为字节流
    raw_bytes = b58decode(base58_string)

    # 转换为整数列表
    byte_array = list(raw_bytes)

    # 保存为 JSON 文件
    with open("id.json", "w") as f:
        json.dump(byte_array, f)

    print("✅ 转换成功！私钥已保存为 id.json")
    print(f"前 10 位数据样例: {byte_array[:10]}...")
except Exception as e:
    print(f"❌ 转换失败: {e}")