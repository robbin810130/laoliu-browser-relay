"""
Phoenix Relay Server - Extension WebSocket 端点
处理 Chrome Extension 的连接、握手、消息收发
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from . import config
from .crypto import CryptoManager, CryptoError
from .target_manager import TargetManager
from .router import CDPRouter
from .models import HelloParams

logger = logging.getLogger(__name__)


class ExtensionConnection:
    """Extension WebSocket 连接管理器"""

    def __init__(
        self,
        crypto: CryptoManager,
        target_manager: TargetManager,
        router: CDPRouter,
    ):
        self._crypto = crypto
        self._tm = target_manager
        self._router = router
        self._ws: Optional[WebSocket] = None
        self._connected = False
        self._handshake_done = False
        self._ping_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    # ============================================================
    # 连接处理
    # ============================================================
    async def handle_connection(self, ws: WebSocket, existing_ws: WebSocket | None = None):
        """
        处理 Extension WebSocket 连接

        如果已有 Extension 连接，关闭旧连接
        """
        # 如果已有连接，关闭旧连接
        if existing_ws:
            try:
                await existing_ws.close(code=1000, reason="New extension connected")
            except Exception:
                pass

        self._ws = ws
        self._connected = True
        self._handshake_done = False

        # 取消断连宽限期
        self._tm.cancel_grace_period()

        # 设置 Router 的发送函数
        self._router.set_send_to_extension(self._send_message)

        logger.info("Extension WebSocket 已连接，等待握手...")

        try:
            # 等待握手（5秒超时）
            await self._wait_for_handshake()

            # 启动心跳
            self._ping_task = asyncio.create_task(self._ping_loop())

            # 消息循环
            await self._message_loop()

        except WebSocketDisconnect:
            logger.info("Extension WebSocket 断开")
        except asyncio.TimeoutError:
            logger.warning("握手超时，关闭连接")
            await self._close(4001, "Handshake timeout")
        except Exception as e:
            import traceback
            logger.error(f"Extension 连接异常: {e}\n{traceback.format_exc()}")
        finally:
            await self._on_disconnect()

    # ============================================================
    # 握手
    # ============================================================
    async def _wait_for_handshake(self):
        """等待 Extension.hello 消息"""
        deadline = time.time() + config.HANDSHAKE_TIMEOUT_MS / 1000

        while time.time() < deadline:
            raw = await asyncio.wait_for(
                self._ws.receive_text(),
                timeout=max(0.1, deadline - time.time()),
            )

            # 解密
            if self._crypto.is_encryption_active:
                raw = self._crypto.decrypt(raw)

            msg = json.loads(raw)
            method = msg.get("method", "")

            if method == "Extension.hello":
                await self._handle_hello(msg)
                return
            else:
                logger.warning(f"握手阶段收到非 hello 消息: {method}")

        raise asyncio.TimeoutError("握手超时")

    async def _handle_hello(self, msg: dict):
        """处理 Extension.hello"""
        params = msg.get("params", {})
        hello = HelloParams(**params)

        # 调试日志
        logger.info(f"收到 Extension.hello: protocolVersion={hello.protocolVersion}, "
                     f"extensionVersion={hello.extensionVersion}, "
                     f"hasEncryptedSessionKey={hello.encryptedSessionKey is not None}, "
                     f"encryptedSessionKey长度={len(hello.encryptedSessionKey) if hello.encryptedSessionKey else 0}")

        # 检查协议版本
        if hello.protocolVersion != config.PROTOCOL_VERSION:
            logger.warning(
                f"协议版本不匹配: expected={config.PROTOCOL_VERSION}, got={hello.protocolVersion}"
            )
            # Accio Desktop 行为：请求 Extension reload
            ack = {
                "method": "Extension.helloAck",
                "params": {
                    "status": "version_mismatch",
                    "action": "reload",
                    "reloadTargetKey": "phoenix-relay",
                },
            }
            await self._send_message(ack)
            await self._close(4001, "Protocol version mismatch")
            return

        # 解密 session key
        encrypted = False
        if hello.encryptedSessionKey:
            try:
                self._crypto.decrypt_session_key(hello.encryptedSessionKey)
                encrypted = True
                logger.info("Session key 解密成功，加密链已建立 ✅")
            except CryptoError as e:
                logger.warning(f"Session key 解密失败: {e}")
                # Extension 不接受不加密的 helloAck，所以必须加密成功
                await self._close(4001, "Session key decryption failed")
                return

        # 发送 helloAck
        ack_params = {"status": "ok", "encrypted": encrypted}
        ack = {"method": "Extension.helloAck", "params": ack_params}
        await self._send_message(ack)

        self._handshake_done = True
        logger.info(f"握手完成 ✅ encrypted={encrypted}")

    # ============================================================
    # 心跳
    # ============================================================
    async def _ping_loop(self):
        """每 5 秒发送 ping"""
        try:
            while self._connected:
                await self._send_message({"method": "ping"})
                await asyncio.sleep(config.PING_INTERVAL_MS / 1000)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Ping 循环异常: {e}")

    # ============================================================
    # 消息循环
    # ============================================================
    async def _message_loop(self):
        """Extension → Relay 消息循环"""
        while self._connected:
            try:
                raw = await self._ws.receive_text()
            except WebSocketDisconnect:
                break

            # 解密
            if self._crypto.is_encryption_active:
                try:
                    raw = self._crypto.decrypt(raw)
                except CryptoError as e:
                    logger.error(f"消息解密失败: {e}")
                    continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"无效 JSON: {raw[:100]}")
                continue

            await self._handle_message(msg)

    async def _handle_message(self, msg: dict):
        """处理 Extension 发来的消息"""
        method = msg.get("method", "")

        # pong 响应
        if method == "pong":
            return

        # CDP 事件转发（Extension.tabDiscovered/Updated/Removed 也在 forwardCDPEvent 内）
        elif method == "forwardCDPEvent":
            inner_method = msg.get("params", {}).get("method", "")
            logger.info(f"← forwardCDPEvent: {inner_method}")
            await self._router.handle_cdp_event(msg)

        # 命令响应
        elif "id" in msg and ("result" in msg or "error" in msg):
            logger.info(f"← Extension 响应: id={msg.get('id')}")
            await self._router.handle_extension_response(msg)

        # 直接 Tab 事件（兼容旧版，正常情况下 Extension 通过 forwardCDPEvent 发送）
        elif method == "Extension.tabDiscovered":
            logger.info(f"← Extension.tabDiscovered (direct)")
            self._tm.handle_tab_discovered(msg.get("params", {}))
        elif method == "Extension.tabUpdated":
            self._tm.handle_tab_updated(msg.get("params", {}))
        elif method == "Extension.tabRemoved":
            self._tm.handle_tab_removed(msg.get("params", {}))

        else:
            logger.debug(f"未处理的 Extension 消息: {method}")

    # ============================================================
    # 发送消息
    # ============================================================
    async def _send_message(self, msg: dict):
        """发送消息给 Extension（自动加密）"""
        if not self._ws:
            return

        payload = json.dumps(msg, ensure_ascii=False)

        # 加密
        if self._crypto.is_encryption_active:
            payload = self._crypto.encrypt(payload)

        try:
            await self._ws.send_text(payload)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    # ============================================================
    # 断连处理
    # ============================================================
    async def _on_disconnect(self):
        """Extension 断开后的处理"""
        self._connected = False
        self._handshake_done = False

        # 停止心跳
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            self._ping_task = None

        # 清理等待中的命令
        self._router.clear_pending()

        # 重置加密状态（下次连接会重新握手）
        self._crypto.reset()

        # 启动断连宽限期
        await self._tm.start_grace_period()

        logger.info("Extension 已断开，启动宽限期计时")

    async def _close(self, code: int = 1000, reason: str = ""):
        """关闭 WebSocket 连接"""
        try:
            await self._ws.close(code=code, reason=reason)
        except Exception:
            pass
