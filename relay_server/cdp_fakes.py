"""
Phoenix Relay Server - 伪 CDP 命令实现
Relay Server 本地处理的 CDP 命令（不转发给 Extension）
"""
from __future__ import annotations
import logging
from typing import Any

from . import config
from .target_manager import TargetManager

logger = logging.getLogger(__name__)


class CDPFakeCommands:
    """伪 CDP 命令处理器"""

    def __init__(self, target_manager: TargetManager):
        self._tm = target_manager
        # 注册伪命令处理器
        self._handlers: dict[str, callable] = {
            "Browser.getVersion": self._browser_get_version,
            "Target.getTargets": self._target_get_targets,
            "Target.getBrowserContexts": self._target_get_browser_contexts,
            "Target.getTargetInfo": self._target_get_target_info,
            "Target.setAutoAttach": self._noop,
            "Target.setDiscoverTargets": self._noop,
            "Target.setRemoteLocations": self._noop,
            "Browser.setDownloadBehavior": self._noop,
            "Page.enable": self._noop,
            "Page.disable": self._noop,
            "Log.enable": self._noop,
            "Log.disable": self._noop,
            "Inspector.enable": self._noop,
            "Inspector.disable": self._noop,
            "Performance.enable": self._noop,
            "Performance.disable": self._noop,
            "Network.enable": self._noop,
            "Network.disable": self._noop,
            "DOM.enable": self._noop,
            "Runtime.enable": self._noop,
        }

    def is_fake_command(self, method: str) -> bool:
        """判断是否为伪命令（本地处理，不转发给 Extension）"""
        return method in self._handlers

    async def handle(self, method: str, params: dict | None = None) -> dict:
        """处理伪 CDP 命令，返回 result"""
        handler = self._handlers.get(method)
        if handler:
            return await handler(params or {})
        raise ValueError(f"未知伪命令: {method}")

    # ============================================================
    # 具体命令实现
    # ============================================================
    async def _browser_get_version(self, params: dict) -> dict:
        """Browser.getVersion — 伪造浏览器版本信息"""
        return {
            "protocolVersion": config.CDP_PROTOCOL_VERSION,
            "product": config.PRODUCT_NAME,
            "revision": "@phoenix-relay",
            "userAgent": f"{config.PRODUCT_NAME}/1.0",
            "jsVersion": "1.0",
        }

    async def _target_get_targets(self, params: dict) -> dict:
        """Target.getTargets — 返回所有 targets（含 virtual 和 physical）"""
        targets = self._tm.get_all_targets()
        target_infos = []
        for t in targets:
            target_infos.append({
                "targetId": t.targetId,
                "type": t.type,
                "title": t.title,
                "url": t.url,
                "attached": t.attached,
                "browserContextId": t.browserContextId or "",
            })
        return {"targetInfos": target_infos}

    async def _target_get_browser_contexts(self, params: dict) -> dict:
        """Target.getBrowserContexts — 空的浏览器上下文"""
        return {"browserContextIds": []}

    async def _target_get_target_info(self, params: dict) -> dict:
        """Target.getTargetInfo — 查找 target 信息"""
        target_id = params.get("targetId", "")
        session_id = params.get("sessionId", "")

        info = None
        if target_id:
            info = self._tm.get_target_by_target_id(target_id)
        elif session_id:
            info = self._tm.get_target_by_session_id(session_id)

        if info:
            return {
                "targetInfo": {
                    "targetId": info.targetId,
                    "type": info.type,
                    "title": info.title,
                    "url": info.url,
                    "attached": info.attached,
                    "browserContextId": info.browserContextId or "",
                }
            }
        return {"targetInfo": {}}

    async def _noop(self, params: dict) -> dict:
        """空操作 — 大部分 enable/disable 命令返回空对象"""
        return {}
