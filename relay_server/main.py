"""
LaoLiu Relay Server - 主程序入口
FastAPI app + uvicorn 启动 + HTTP 端点 + WebSocket 端点注册
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .crypto import CryptoManager
from .target_manager import TargetManager
from .cdp_fakes import CDPFakeCommands
from .router import CDPRouter
from .ws_extension import ExtensionConnection
from .ws_cdp import CDPConnection

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("laoliu-relay")

# ============================================================
# 全局组件
# ============================================================
crypto = CryptoManager()
target_manager = TargetManager()
fake_commands = CDPFakeCommands(target_manager)
router = CDPRouter(crypto, target_manager, fake_commands)
ext_connection = ExtensionConnection(crypto, target_manager, router)
cdp_connection = CDPConnection(router)

# Extension 断连后通知 CDP 客户端
target_manager.set_on_targets_cleared(cdp_connection.notify_all_disconnected)

# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(title="LaoLiu Relay Server", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HTTP 端点
# ============================================================

@app.head("/")
async def head_root():
    """Extension 预检（连接前探测）"""
    return {}


@app.get("/")
async def get_root():
    """健康检查"""
    return "OK"


@app.get("/status")
async def get_status():
    """连接状态"""
    return {
        "extension_connected": ext_connection.is_connected,
        "encryption_active": crypto.is_encryption_active,
        "targets": target_manager.get_status(),
        "config": config.get_config_summary(),
    }


@app.get("/json/list")
async def get_json_list():
    """标签页列表（CDP 兼容格式）"""
    return target_manager.get_target_list_json()


@app.get("/json/close/{target_id}")
async def close_target(target_id: str):
    """关闭标签页"""
    info = target_manager.get_target_by_target_id(target_id)
    if not info:
        return {"error": f"Target not found: {target_id}"}

    # 发送关闭命令给 Extension
    await ext_connection._send_message({
        "id": 0,
        "method": "Extension.closeTab",
        "params": {"targetId": target_id},
    })
    return {"result": "closing"}


@app.get("/json/version")
async def get_json_version():
    """版本信息（CDP 兼容）"""
    return {
        "Browser": f"{config.PRODUCT_NAME}/1.0",
        "Protocol-Version": config.CDP_PROTOCOL_VERSION,
        "User-Agent": f"{config.PRODUCT_NAME}/1.0",
        "WebKit-Version": "1.0",
    }


# ============================================================
# WebSocket 端点
# ============================================================

@app.websocket("/extension")
async def ws_extension(ws: WebSocket):
    """Extension WebSocket 端点"""
    # Origin 校验
    origin = ws.headers.get("origin", "")
    if not origin.startswith(config.ALLOWED_ORIGINS_PREFIX):
        # 允许无 origin（某些客户端）和 chrome-extension:// 来源
        if origin:  # 有 origin 但不是 chrome-extension
            logger.warning(f"Extension 连接 origin 校验失败: {origin}")
            await ws.close(code=4003, reason="Invalid origin")
            return

    await ws.accept()
    await ext_connection.handle_connection(ws)


@app.websocket("/cdp")
async def ws_cdp(ws: WebSocket, token: str = Query(default="")):
    """CDP WebSocket 端点（Agent/Playwright 连接）"""
    await cdp_connection.handle_connection(ws, token=token)


# ============================================================
# 启动
# ============================================================

def main():
    """启动 Relay Server"""
    logger.info("=" * 60)
    logger.info("  LaoLiu Relay Server")
    logger.info(f"  监听: ws://{config.RELAY_HOST}:{config.RELAY_PORT}")
    logger.info(f"  Extension 端点: ws://{config.RELAY_HOST}:{config.RELAY_PORT}/extension")
    logger.info(f"  CDP 端点: ws://{config.RELAY_HOST}:{config.RELAY_PORT}/cdp?token=<TOKEN>")
    logger.info(f"  Auth Token: {config.AUTH_TOKEN[:8]}...")
    logger.info(f"  加密: {'已启用' if crypto.is_encryption_active else '等待握手'}")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=config.RELAY_HOST,
        port=config.RELAY_PORT,
        log_level="info",
        ws_ping_interval=None,  # 我们自己管理心跳
    )


if __name__ == "__main__":
    main()
