"""
LaoLiu Relay Server - Target 管理器
管理 Extension 上报的标签页（virtual + physical）

Extension 的 tab 管理使用 targetId + sessionId，不用 Chrome tabId。
- virtual tab: Extension 发现的 tab，targetId 格式 "vtab-{tabId}"
- physical tab: 已 attach debugger 的 tab，targetId 为 Chrome 真实 targetId

数据结构:
  targetId(str) → TargetInfo
  sessionId(str) → targetId(str)  映射
"""
from __future__ import annotations
import asyncio
import logging
from typing import Callable, Optional

from .models import TargetInfo
from . import config

logger = logging.getLogger(__name__)


class TargetManager:
    """管理所有已连接的标签页"""

    def __init__(self):
        # targetId → TargetInfo
        self._targets: dict[str, TargetInfo] = {}
        # sessionId → targetId 映射
        self._session_to_target: dict[str, str] = {}
        # 断连宽限期计时器
        self._grace_task: Optional[asyncio.Task] = None
        # 断连回调
        self._on_targets_cleared: Optional[Callable] = None

    @property
    def targets(self) -> dict[str, TargetInfo]:
        return self._targets

    def set_on_targets_cleared(self, callback: Callable):
        """设置 Extension 断连后的清理回调"""
        self._on_targets_cleared = callback

    # ============================================================
    # Tab 事件处理
    # ============================================================
    def handle_tab_discovered(self, params: dict) -> TargetInfo:
        """
        处理 Extension.tabDiscovered 事件

        Extension 发送格式:
        {
          sessionId: "cb-tab-1-110",
          targetInfo: { targetId: "vtab-110", type: "page", title: "...", url: "...", attached: false }
        }
        """
        session_id = params.get("sessionId", "")
        target_info_data = params.get("targetInfo", {})
        target_id = target_info_data.get("targetId", "")

        if not target_id:
            logger.warning(f"Tab discovered 没有 targetId: {params}")
            return None

        info = TargetInfo(
            targetId=target_id,
            type=target_info_data.get("type", "page"),
            title=target_info_data.get("title", ""),
            url=target_info_data.get("url", ""),
            attached=target_info_data.get("attached", False),
            sessionId=session_id,
            physical=False,
        )
        self._targets[target_id] = info
        if session_id:
            self._session_to_target[session_id] = target_id

        logger.info(f"Tab discovered: targetId={target_id}, url={info.url[:80]}")
        return info

    def handle_tab_updated(self, params: dict):
        """
        处理 Extension.tabUpdated 事件

        Extension 发送格式:
        {
          sessionId: "cb-tab-1-110",
          targetInfo: { targetId: "vtab-110", type: "page", title: "...", url: "...", attached: false }
        }
        """
        session_id = params.get("sessionId", "")
        target_info_data = params.get("targetInfo", {})
        target_id = target_info_data.get("targetId", "")

        # 先通过 sessionId 找 target
        lookup_id = target_id or self._session_to_target.get(session_id)
        if lookup_id and lookup_id in self._targets:
            info = self._targets[lookup_id]
            if target_info_data.get("url"):
                info.url = target_info_data["url"]
            if target_info_data.get("title"):
                info.title = target_info_data["title"]
            if "attached" in target_info_data:
                info.attached = target_info_data["attached"]
            logger.debug(f"Tab updated: targetId={lookup_id}")
        else:
            logger.debug(f"Tab updated 但 target 未找到: sessionId={session_id}, targetId={target_id}")

    def handle_tab_removed(self, params: dict):
        """
        处理 Extension.tabRemoved 事件

        Extension 发送格式: { sessionId: "cb-tab-1-110" }
        """
        session_id = params.get("sessionId", "")
        target_id = self._session_to_target.pop(session_id, None)
        if target_id:
            info = self._targets.pop(target_id, None)
            if info:
                logger.info(f"Tab removed: targetId={target_id}")

    # ============================================================
    # Target 事件处理
    # ============================================================
    def handle_attached_to_target(self, params: dict):
        """
        处理 Target.attachedToTarget 事件 — 标记为 physical

        Extension 发送格式:
        {
          sessionId: "cb-tab-1-110",
          targetInfo: { targetId: "real-target-id", type: "page", ... },
          waitingForDebugger: false
        }
        """
        session_id = params.get("sessionId", "")
        target_info_data = params.get("targetInfo", {})

        # 通过 sessionId 查找已有的 virtual target
        virtual_target_id = self._session_to_target.get(session_id)

        if virtual_target_id and virtual_target_id in self._targets:
            info = self._targets[virtual_target_id]
            info.physical = True
            info.attached = True

            # 如果 realTargetId 不同，更新映射
            real_target_id = target_info_data.get("targetId", "")
            if real_target_id and real_target_id != virtual_target_id:
                # 重新映射
                self._targets.pop(virtual_target_id, None)
                info.targetId = real_target_id
                self._targets[real_target_id] = info
                self._session_to_target[session_id] = real_target_id

            logger.info(f"Target attached: sessionId={session_id}, physical=True, targetId={info.targetId}")
        else:
            # 新 attach 的 target（可能是之前未 discover 的）
            real_target_id = target_info_data.get("targetId", "")
            if real_target_id:
                info = TargetInfo(
                    targetId=real_target_id,
                    type=target_info_data.get("type", "page"),
                    title=target_info_data.get("title", ""),
                    url=target_info_data.get("url", ""),
                    attached=True,
                    sessionId=session_id,
                    physical=True,
                )
                self._targets[real_target_id] = info
                self._session_to_target[session_id] = real_target_id
                logger.info(f"Target attached (new): sessionId={session_id}, targetId={real_target_id}")

    def handle_detached_from_target(self, params: dict):
        """处理 Target.detachedFromTarget 事件"""
        session_id = params.get("sessionId", "")
        target_id = self._session_to_target.get(session_id)
        if target_id and target_id in self._targets:
            info = self._targets[target_id]
            info.physical = False
            info.attached = False
            logger.info(f"Target detached: sessionId={session_id}, targetId={target_id}")

    # ============================================================
    # 查询
    # ============================================================
    def get_physical_targets(self) -> list[TargetInfo]:
        """返回所有 physical=true 的 targets"""
        return [t for t in self._targets.values() if t.physical]

    def get_all_targets(self) -> list[TargetInfo]:
        """返回所有 targets"""
        return list(self._targets.values())

    def get_target_by_session_id(self, session_id: str) -> Optional[TargetInfo]:
        """通过 sessionId 查找 target"""
        target_id = self._session_to_target.get(session_id)
        if target_id:
            return self._targets.get(target_id)
        return None

    def get_target_by_target_id(self, target_id: str) -> Optional[TargetInfo]:
        """通过 targetId 查找 target"""
        return self._targets.get(target_id)

    def get_target_list_json(self) -> list[dict]:
        """返回 /json/list 格式的 target 列表"""
        result = []
        for info in self._targets.values():
            result.append({
                "id": info.targetId,
                "type": info.type,
                "title": info.title,
                "url": info.url,
                "webSocketDebuggerUrl": f"ws://{config.RELAY_HOST}:{config.RELAY_PORT}/cdp",
            })
        return result

    # ============================================================
    # 断连宽限期
    # ============================================================
    async def start_grace_period(self):
        """Extension 断连后启动 8 秒宽限期"""
        self.cancel_grace_period()
        logger.info(f"断连宽限期启动 ({config.RECONNECT_GRACE_MS}ms)")

        async def _grace_period_task():
            await asyncio.sleep(config.RECONNECT_GRACE_MS / 1000)
            logger.warning("断连宽限期到期，清理所有 targets")
            self.clear_all()
            if self._on_targets_cleared:
                await self._on_targets_cleared()

        self._grace_task = asyncio.create_task(_grace_period_task())

    def cancel_grace_period(self):
        """取消宽限期（Extension 重连时调用）"""
        if self._grace_task and not self._grace_task.done():
            self._grace_task.cancel()
            self._grace_task = None
            logger.info("断连宽限期已取消（Extension 重连）")

    def clear_all(self):
        """清理所有 target 状态"""
        self._targets.clear()
        self._session_to_target.clear()

    # ============================================================
    # 统计
    # ============================================================
    def get_status(self) -> dict:
        return {
            "total_targets": len(self._targets),
            "physical_targets": len(self.get_physical_targets()),
            "session_mappings": len(self._session_to_target),
        }
