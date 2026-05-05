"""
LaoLiu Relay Server - CDP WebSocket 端点
Agent/Playwright 连接的 CDP 端点
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect, Query

from . import config
from .router import CDPRouter
from .models import CDPRequest

logger = logging.getLogger(__name__)


class CDPConnection:
    """CDP 客户端连接管理器"""

    def __init__(self, router: CDPRouter):
        self._router = router
        self._clients: list[WebSocket] = []

    # ============================================================
    # 连接处理
    # ============================================================
    async def handle_connection(self, ws: WebSocket, token: str | None = None):
        """
        处理 CDP WebSocket 连接

        认证方式：HTTP Header Authorization: Bearer <token>
        或 Query 参数 ?token=<token>
        """
        # Token 认证
        if config.AUTH_TOKEN:
            # 从 query 参数获取 token（WebSocket 不方便传 Header）
            # 也支持 HTTP Header Authorization: Bearer <token>
            auth_header = ws.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

            # URL 解码 token（base64url 中的 = 可能被编码）
            from urllib.parse import unquote
            decoded_token = unquote(token) if token else ""

            if decoded_token != config.AUTH_TOKEN:
                await ws.close(code=4003, reason="Unauthorized")
                logger.warning("CDP 连接认证失败")
                return

        await ws.accept()
        self._clients.append(ws)
        logger.info(f"CDP 客户端已连接，当前共 {len(self._clients)} 个客户端")

        # 设置广播函数
        self._router.set_broadcast_to_cdp(self._broadcast)

        try:
            await self._message_loop(ws)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"CDP 客户端异常: {e}")
        finally:
            self._clients.remove(ws)
            logger.info(f"CDP 客户端已断开，剩余 {len(self._clients)} 个客户端")

    # ============================================================
    # 消息循环
    # ============================================================
    async def _message_loop(self, ws: WebSocket):
        """CDP 客户端 → Relay 消息循环"""
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"CDP 客户端发送无效 JSON: {raw[:100]}")
                continue

            request = CDPRequest(**msg)

            # 路由命令
            response = await self._router.handle_cdp_request(request)
            if response:
                await ws.send_json(response)

    # ============================================================
    # 广播
    # ============================================================
    async def _broadcast(self, msg: dict):
        """广播 CDP 事件给所有连接的客户端"""
        method = msg.get("method", "")
        payload = json.dumps(msg, ensure_ascii=False)
        dead_clients = []

        for client in self._clients:
            try:
                await client.send_text(payload)
                logger.debug(f"广播事件给 CDP 客户端: {method}")
            except Exception as e:
                logger.debug(f"广播失败: {e}")
                dead_clients.append(client)

        # 清理断开的客户端
        for client in dead_clients:
            if client in self._clients:
                self._clients.remove(client)

    # ============================================================
    # 通知所有客户端断连
    # ============================================================
    async def notify_all_disconnected(self):
        """Extension 断连后通知所有 CDP 客户端"""
        for client in self._clients[:]:
            try:
                await client.close(code=1000, reason="Extension disconnected")
            except Exception:
                pass
        self._clients.clear()
