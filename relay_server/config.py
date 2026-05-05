"""
Phoenix Relay Server - 配置模块
自建 Relay Server，替代 Accio Desktop 的 WebSocket Relay
"""
import os
import secrets
import base64
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent
KEYS_DIR = BASE_DIR / "keys"
KEYS_DIR.mkdir(parents=True, exist_ok=True)  # 自动创建 keys 目录
PRIVATE_KEY_PATH = KEYS_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public_key.pem"

# ============================================================
# 网络配置
# ============================================================
RELAY_HOST = "127.0.0.1"        # 只监听 loopback
RELAY_PORT = 9236                # 默认端口（与 Accio 一致）
RELAY_PORT_ALT = 9237            # 备用端口

# ============================================================
# 超时配置（与 Accio 对齐）
# ============================================================
HANDSHAKE_TIMEOUT_MS = 5000      # 握手超时 5 秒
PING_INTERVAL_MS = 5000          # 心跳间隔 5 秒
COMMAND_TIMEOUT_MS = 30000       # CDP 命令超时 30 秒
COMMAND_LONG_TIMEOUT_MS = 60000  # 长命令超时 60 秒
MESSAGE_EXPIRY_MS = 130000       # 消息过期 130 秒
RECONNECT_GRACE_MS = 8000        # 断连宽限期 8 秒

# ============================================================
# 加密配置
# ============================================================
AES_KEY_SIZE = 32                # AES-256
AES_IV_SIZE = 12                 # GCM IV 12 字节
AES_TAG_SIZE = 16                # GCM Auth Tag 16 字节
WIRE_PREFIX = "E:"              # 加密消息前缀

# ============================================================
# 认证配置
# ============================================================
def _generate_auth_token() -> str:
    """生成随机 authToken（32字节 base64url）"""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")

AUTH_TOKEN = os.environ.get("PHOENIX_RELAY_TOKEN", _generate_auth_token())

# 将 token 写入文件，方便其他组件读取
_token_file = KEYS_DIR / ".auth_token"
_token_file.write_text(AUTH_TOKEN)

# ============================================================
# 协议配置
# ============================================================
PROTOCOL_VERSION = 1
PRODUCT_NAME = "Phoenix-Extension-Relay"
CDP_PROTOCOL_VERSION = "1.3"

# ============================================================
# Origin 校验
# ============================================================
ALLOWED_ORIGINS_PREFIX = "chrome-extension://"

# ============================================================
# 队列配置
# ============================================================
MAX_QUEUE_DEPTH = 100            # per-tab 命令队列深度


def get_config_summary() -> dict:
    """返回配置摘要（不暴露敏感信息）"""
    return {
        "host": RELAY_HOST,
        "port": RELAY_PORT,
        "auth_token_set": bool(AUTH_TOKEN),
        "private_key_exists": PRIVATE_KEY_PATH.exists(),
        "protocol_version": PROTOCOL_VERSION,
    }
