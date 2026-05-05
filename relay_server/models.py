"""
LaoLiu Relay Server - Pydantic 消息模型
定义所有 WebSocket 消息的数据结构
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ============================================================
# 基础消息
# ============================================================
class RelayMessage(BaseModel):
    """Relay 通用消息"""
    id: Optional[int] = None
    method: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    ts: Optional[int] = None  # Unix ms 时间戳


# ============================================================
# 握手消息
# ============================================================
class HelloParams(BaseModel):
    """Extension.hello 的 params"""
    protocolVersion: int = 1
    extensionVersion: str = "0.0.0"
    encryptedSessionKey: str = ""  # Base64 编码的加密 session key


class HelloAckParams(BaseModel):
    """Extension.helloAck 的 params"""
    status: str = "ok"
    encrypted: bool = True
    action: Optional[str] = None       # "reload" 等
    reloadTargetKey: Optional[str] = None


# ============================================================
# CDP 命令/事件
# ============================================================
class ForwardCDPCommandParams(BaseModel):
    """forwardCDPCommand 的 params"""
    method: str
    sessionId: Optional[str] = None
    params: Optional[dict[str, Any]] = None


class ForwardCDPEventParams(BaseModel):
    """forwardCDPEvent 的 params"""
    sessionId: Optional[str] = None
    method: str = ""
    params: Optional[dict[str, Any]] = None


# ============================================================
# Tab 事件（Extension 通过 forwardCDPEvent 发送）
# 实际格式参考 laoliu-browser-relay/lib/cdp/tabs/manager.js:
#   Extension.tabDiscovered: { sessionId, targetInfo: { targetId, type, title, url, attached } }
#   Extension.tabUpdated:   { sessionId, targetInfo: { targetId, type, title, url, attached } }
#   Extension.tabRemoved:   { sessionId }
# ============================================================
class TabDiscoveredParams(BaseModel):
    """Extension.tabDiscovered 的 params"""
    sessionId: str = ""
    targetInfo: Optional[dict[str, Any]] = None


class TabUpdatedParams(BaseModel):
    """Extension.tabUpdated 的 params"""
    sessionId: str = ""
    targetInfo: Optional[dict[str, Any]] = None


class TabRemovedParams(BaseModel):
    """Extension.tabRemoved 的 params"""
    sessionId: str = ""


# ============================================================
# Target 事件
# ============================================================
class AttachedToTargetParams(BaseModel):
    """Target.attachedToTarget 的 params"""
    sessionId: str
    targetInfo: Optional[dict[str, Any]] = None


class DetachedFromTargetParams(BaseModel):
    """Target.detachedFromTarget 的 params"""
    sessionId: str


# ============================================================
# Target Info
# ============================================================
class TargetInfo(BaseModel):
    """CDP Target 信息"""
    targetId: str
    type: str = "page"
    title: str = ""
    url: str = ""
    attached: bool = False
    sessionId: Optional[str] = None
    browserContextId: Optional[str] = None
    physical: bool = False  # 是否已物理 attach


# ============================================================
# CDP 客户端消息
# ============================================================
class CDPRequest(BaseModel):
    """CDP 客户端发来的标准 CDP 请求"""
    id: int
    method: str
    params: Optional[dict[str, Any]] = None
    sessionId: Optional[str] = None
