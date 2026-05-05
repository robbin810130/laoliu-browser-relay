"""
LaoLiu Relay Server - CDP 命令路由
CDP 命令转发 + 事件分发 + 消息 ID 映射
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Optional

from . import config
from .crypto import CryptoManager
from .target_manager import TargetManager
from .cdp_fakes import CDPFakeCommands
from .models import CDPRequest

logger = logging.getLogger(__name__)


class CDPRouter:
    """CDP 命令路由器"""

    def __init__(
        self,
        crypto: CryptoManager,
        target_manager: TargetManager,
        fake_commands: CDPFakeCommands,
    ):
        self._crypto = crypto
        self._tm = target_manager
        self._fakes = fake_commands

        # 消息 ID 映射: cdp_client_id → extension_id
        self._id_map: dict[int, int] = {}
        # 反向映射: extension_id → cdp_client_id
        self._id_reverse: dict[int, int] = {}
        # 自增 ID（用于发送给 Extension 的命令）
        self._next_id = 1
        # 等待响应的命令: extension_id → asyncio.Future
        self._pending_commands: dict[int, asyncio.Future] = {}
        # Extension WebSocket 发送函数
        self._send_to_extension = None
        # CDP 客户端广播函数
        self._broadcast_to_cdp = None

    def set_send_to_extension(self, fn):
        self._send_to_extension = fn

    def set_broadcast_to_cdp(self, fn):
        self._broadcast_to_cdp = fn

    # ============================================================
    # CDP 客户端 → Extension
    # ============================================================
    async def handle_cdp_request(self, request: CDPRequest) -> dict | None:
        """
        处理 CDP 客户端发来的请求

        1. 伪命令 → 本地处理并返回
        2. Extension 命令 → 转发给 Extension
        3. CDP 命令 → forwardCDPCommand 转发
        """
        method = request.method
        params = request.params or {}
        session_id = request.sessionId

        # 检查是否为伪命令
        if self._fakes.is_fake_command(method):
            result = await self._fakes.handle(method, params)
            return {"id": request.id, "result": result}

        # 检查是否为 Extension 虚拟命令
        if method.startswith("Extension."):
            return await self._route_extension_command(request)

        # ── Target.attachToTarget → 转换为 Extension.ensureAttach ──
        # Relay Server 需要拦截此命令，因为 vtab-* 虚拟标签不能直接
        # 通过 chrome.debugger 转发（标签还未 attach）。
        if method == "Target.attachToTarget":
            return await self._handle_attach_to_target(request)

        # 标准 CDP 命令 → forwardCDPCommand 转发给 Extension
        ext_id = self._allocate_id()
        self._id_map[request.id] = ext_id
        self._id_reverse[ext_id] = request.id

        # 构建转发消息
        forward_msg = {
            "id": ext_id,
            "ts": int(time.time() * 1000),
            "method": "forwardCDPCommand",
            "params": {
                "method": method,
                "params": params,
            },
        }
        if session_id:
            forward_msg["params"]["sessionId"] = session_id

        # 创建 Future 等待响应
        future = asyncio.get_event_loop().create_future()
        self._pending_commands[ext_id] = future

        # 发送给 Extension
        await self._send_to_extension(forward_msg)

        # 等待响应（带超时）
        try:
            result = await asyncio.wait_for(
                future, timeout=config.COMMAND_TIMEOUT_MS / 1000
            )
            return {"id": request.id, **result}
        except asyncio.TimeoutError:
            self._pending_commands.pop(ext_id, None)
            self._id_map.pop(request.id, None)
            self._id_reverse.pop(ext_id, None)
            return {"id": request.id, "error": f"CDP command timeout: {method}"}

    # ============================================================
    # Extension → CDP 客户端（命令响应）
    # ============================================================
    async def handle_extension_response(self, msg: dict):
        """处理 Extension 返回的命令响应"""
        ext_id = msg.get("id")
        if ext_id is None:
            return

        future = self._pending_commands.pop(ext_id, None)
        if future and not future.done():
            # 构建响应（映射 ID 回 CDP 客户端的 ID）
            response = {}
            if "result" in msg:
                response["result"] = msg["result"]
            elif "error" in msg:
                response["error"] = msg["error"]
            future.set_result(response)

            # 清理映射
            cdp_id = self._id_reverse.pop(ext_id, None)
            if cdp_id:
                self._id_map.pop(cdp_id, None)

    # ============================================================
    # Extension → CDP 客户端（CDP 事件）
    # ============================================================
    async def handle_cdp_event(self, msg: dict):
        """处理 Extension 上报的 CDP 事件（forwardCDPEvent）"""
        params = msg.get("params", {})
        method = params.get("method", "")
        event_params = params.get("params", {})
        session_id = params.get("sessionId")

        # 处理 Tab 发现/更新/移除事件
        if method == "Extension.tabDiscovered":
            self._tm.handle_tab_discovered(event_params)
        elif method == "Extension.tabUpdated":
            self._tm.handle_tab_updated(event_params)
        elif method == "Extension.tabRemoved":
            self._tm.handle_tab_removed(event_params)

        # 处理 CDP attach/detach 事件
        elif method == "Target.attachedToTarget":
            self._tm.handle_attached_to_target(params)
        elif method == "Target.detachedFromTarget":
            self._tm.handle_detached_from_target(params)

        # 广播给所有 CDP 客户端（包含所有事件类型）
        if self._broadcast_to_cdp is not None:
            event_msg = {"method": method, "params": event_params}
            if session_id:
                event_msg["sessionId"] = session_id
            await self._broadcast_to_cdp(event_msg)

    # ============================================================
    # Target.attachToTarget 拦截
    # ============================================================
    async def _handle_attach_to_target(self, request: CDPRequest) -> dict:
        """
        拦截 Target.attachToTarget，转换为 Extension.ensureAttach。

        标准 CDP 客户端（如 MCP、Playwright）发送 Target.attachToTarget 来
        attach 到标签页。但 vtab-* 虚拟标签尚未被 chrome.debugger attach，
        不能直接转发。因此 Relay Server 将其转换为 Extension.ensureAttach，
        由 Extension 执行 chrome.debugger.attach 并返回 sessionId。
        """
        params = request.params or {}
        target_id = params.get("targetId", "")

        # 如果目标已经在 target_manager 中有 sessionId，直接返回
        existing = self._tm.get_session_id(target_id)
        if existing:
            logger.debug(f"Target.attachToTarget: {target_id} already attached, sessionId={existing}")
            return {"id": request.id, "result": {"sessionId": existing}}

        # 通过 Extension.ensureAttach 请求 attach
        ext_id = self._allocate_id()
        forward_msg = {
            "id": ext_id,
            "ts": int(time.time() * 1000),
            "method": "forwardCDPCommand",
            "params": {
                "method": "Extension.ensureAttach",
                "params": {"targetId": target_id},
            },
        }
        self._id_map[request.id] = ext_id
        self._id_reverse[ext_id] = request.id

        future = asyncio.get_event_loop().create_future()
        self._pending_commands[ext_id] = future

        await self._send_to_extension(forward_msg)

        try:
            result = await asyncio.wait_for(
                future, timeout=config.COMMAND_TIMEOUT_MS / 1000
            )
            # Extension.ensureAttach 返回 { targetId, sessionId }
            ext_result = result.get("result", {})
            session_id = ext_result.get("sessionId", "")
            if session_id:
                # 注册到 target_manager
                self._tm.register_session(target_id, session_id)
            return {"id": request.id, "result": {"sessionId": session_id}}
        except asyncio.TimeoutError:
            self._pending_commands.pop(ext_id, None)
            self._id_map.pop(request.id, None)
            self._id_reverse.pop(ext_id, None)
            return {"id": request.id, "error": "Target.attachToTarget timeout"}

    # ============================================================
    # Extension 虚拟命令路由
    # ============================================================
    async def _route_extension_command(self, request: CDPRequest) -> dict:
        """处理 Extension.* 虚拟命令"""
        method = request.method
        params = request.params or {}

        if method == "Extension.ensureAttach":
            # 请求 Extension attach 到指定 target，等待返回 sessionId
            ext_id = self._allocate_id()
            forward_msg = {
                "id": ext_id,
                "ts": int(time.time() * 1000),
                "method": "Extension.ensureAttach",
                "params": params,
            }
            self._id_map[request.id] = ext_id
            self._id_reverse[ext_id] = request.id

            # 创建 Future 等待 Extension 响应
            future = asyncio.get_event_loop().create_future()
            self._pending_commands[ext_id] = future

            await self._send_to_extension(forward_msg)

            try:
                result = await asyncio.wait_for(
                    future, timeout=config.COMMAND_TIMEOUT_MS / 1000
                )
                return {"id": request.id, **result}
            except asyncio.TimeoutError:
                self._pending_commands.pop(ext_id, None)
                self._id_map.pop(request.id, None)
                self._id_reverse.pop(ext_id, None)
                return {"id": request.id, "error": "Extension.ensureAttach timeout"}

        elif method == "Extension.listTabs":
            ext_id = self._allocate_id()
            forward_msg = {
                "id": ext_id,
                "ts": int(time.time() * 1000),
                "method": "Extension.listTabs",
                "params": {},
            }
            future = asyncio.get_event_loop().create_future()
            self._pending_commands[ext_id] = future
            self._id_map[request.id] = ext_id
            self._id_reverse[ext_id] = request.id

            await self._send_to_extension(forward_msg)

            try:
                result = await asyncio.wait_for(
                    future, timeout=config.COMMAND_TIMEOUT_MS / 1000
                )
                return {"id": request.id, **result}
            except asyncio.TimeoutError:
                return {"id": request.id, "error": "Extension.listTabs timeout"}

        else:
            return {"id": request.id, "error": f"Unknown Extension command: {method}"}

    # ============================================================
    # ID 管理
    # ============================================================
    def _allocate_id(self) -> int:
        """分配自增 ID"""
        id_ = self._next_id
        self._next_id += 1
        return id_

    # ============================================================
    # 消息过期检查
    # ============================================================
    @staticmethod
    def is_message_expired(msg: dict) -> bool:
        """检查消息是否过期（超过 130 秒）"""
        ts = msg.get("ts")
        if ts is None:
            return False  # 没有 ts 字段的消息不做过期检查
        now = int(time.time() * 1000)
        return (now - ts) > config.MESSAGE_EXPIRY_MS

    # ============================================================
    # 清理
    # ============================================================
    def clear_pending(self):
        """清理所有等待中的命令"""
        for future in self._pending_commands.values():
            if not future.done():
                future.set_result({"error": "Connection closed"})
        self._pending_commands.clear()
        self._id_map.clear()
        self._id_reverse.clear()
