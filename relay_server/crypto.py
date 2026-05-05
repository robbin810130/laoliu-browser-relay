"""
Phoenix Relay Server - 加密模块
RSA-OAEP 密钥交换 + AES-256-GCM 传输加密
与 Accio Extension 的 WebCrypto API 完全兼容
"""
from __future__ import annotations
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config


class CryptoManager:
    """加解密管理器"""

    def __init__(self, private_key_path: Path | None = None):
        self._private_key_path = private_key_path or config.PRIVATE_KEY_PATH
        self._private_key = self._load_private_key()
        self._session_key: bytes | None = None
        self._aes_gcm: AESGCM | None = None
        self._encryption_active = False

    # ============================================================
    # 私钥加载
    # ============================================================
    def _load_private_key(self):
        """从 PEM 文件加载 RSA 私钥"""
        pem_data = self._private_key_path.read_bytes()
        key = serialization.load_pem_private_key(pem_data, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("加载的密钥不是 RSA 私钥")
        if key.key_size != 2048:
            raise ValueError(f"RSA 密钥大小应为 2048，实际为 {key.key_size}")
        return key

    # ============================================================
    # 握手：解密 session key
    # ============================================================
    def decrypt_session_key(self, encrypted_session_key_b64: str) -> bool:
        """
        用 RSA-OAEP/SHA-256 解密 Extension 发来的 AES session key

        Chrome WebCrypto RSA-OAEP/SHA-256 默认:
          - hash: SHA-256 (Extension crypto.js 显式指定)
          - MGF1 hash: SHA-256 (Chrome 默认，与主 hash 一致)

        注意: 之前误以为 MGF1 默认用 SHA-1，实测 Chrome 用 SHA-256。
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted_session_key_b64)

            # 方案1: MGF1-SHA256 + SHA-256 (Chrome WebCrypto RSA-OAEP/SHA-256 实际默认)
            try:
                session_key = self._private_key.decrypt(
                    encrypted_bytes,
                    asym_padding.OAEP(
                        mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None,
                    ),
                )
            except Exception:
                # 方案2 fallback: MGF1-SHA1 + SHA-256 (某些旧浏览器可能使用)
                session_key = self._private_key.decrypt(
                    encrypted_bytes,
                    asym_padding.OAEP(
                        mgf=asym_padding.MGF1(algorithm=hashes.SHA1()),
                        algorithm=hashes.SHA256(),
                        label=None,
                    ),
                )

            if len(session_key) != config.AES_KEY_SIZE:
                raise ValueError(
                    f"Session key 长度应为 {config.AES_KEY_SIZE}，实际为 {len(session_key)}"
                )
            self._session_key = session_key
            self._aes_gcm = AESGCM(session_key)
            self._encryption_active = True
            return True
        except Exception as e:
            self._session_key = None
            self._aes_gcm = None
            self._encryption_active = False
            raise CryptoError(f"Session key 解密失败: {e}")

    # ============================================================
    # 加密（Relay → Extension）
    # ============================================================
    def encrypt(self, plaintext: str) -> str:
        """
        AES-256-GCM 加密，返回 wire 格式: "E:" + base64(IV + ciphertext + authTag)

        Extension 端解密逻辑:
          const raw = base64Decode(payload.slice(2))  // 去掉 "E:"
          const iv = raw.slice(0, 12)
          const ciphertext = raw.slice(12, -16)
          const authTag = raw.slice(-16)
        """
        if not self._encryption_active or not self._aes_gcm:
            return plaintext  # 未加密时直接返回明文

        iv = os.urandom(config.AES_IV_SIZE)
        plaintext_bytes = plaintext.encode("utf-8")

        # AESGCM.encrypt 返回 ciphertext + authTag（追加在末尾）
        encrypted = self._aes_gcm.encrypt(iv, plaintext_bytes, None)

        # wire 格式: IV(12) + ciphertext + authTag(16)
        wire_bytes = iv + encrypted  # AESGCM.encrypt 已将 tag 追加在 ciphertext 后
        wire_b64 = base64.b64encode(wire_bytes).decode("ascii")

        return f"{config.WIRE_PREFIX}{wire_b64}"

    # ============================================================
    # 解密（Extension → Relay）
    # ============================================================
    def decrypt(self, wire_message: str) -> str:
        """
        解密 wire 格式的 AES-256-GCM 消息

        wire 格式: "E:" + base64(IV[12] + ciphertext + authTag[16])
        """
        if not wire_message.startswith(config.WIRE_PREFIX):
            return wire_message  # 不是加密消息，直接返回

        if not self._encryption_active or not self._aes_gcm:
            raise CryptoError("收到加密消息但加密未激活")

        # 去掉 "E:" 前缀
        b64_data = wire_message[len(config.WIRE_PREFIX):]
        raw_bytes = base64.b64decode(b64_data)

        if len(raw_bytes) < config.AES_IV_SIZE + config.AES_TAG_SIZE + 1:
            raise CryptoError("加密消息太短")

        # 解析: IV(12) + ciphertext + authTag(16)
        iv = raw_bytes[:config.AES_IV_SIZE]
        ciphertext_with_tag = raw_bytes[config.AES_IV_SIZE:]
        # Python AESGCM.decrypt 接受 ciphertext+tag 格式

        plaintext_bytes = self._aes_gcm.decrypt(iv, ciphertext_with_tag, None)
        return plaintext_bytes.decode("utf-8")

    # ============================================================
    # 状态查询
    # ============================================================
    @property
    def is_encryption_active(self) -> bool:
        return self._encryption_active

    @property
    def public_key_der_b64(self) -> str:
        """返回公钥 DER 的 Base64 编码（用于调试/验证）"""
        pub_key = self._private_key.public_key()
        der = pub_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return base64.b64encode(der).decode("ascii")

    def reset(self):
        """重置加密状态（Extension 断连时调用）"""
        self._session_key = None
        self._aes_gcm = None
        self._encryption_active = False


class CryptoError(Exception):
    """加密相关错误"""
    pass
