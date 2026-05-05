#!/usr/bin/env python3
"""
Phoenix Relay Server - CDP 客户端测试脚本 v2
正确处理异步事件流，测试完整链路
"""
import asyncio
import json
import sys
from urllib.parse import quote

import websockets

RELAY_HOST = "127.0.0.1"
RELAY_PORT = 9236
TOKEN_FILE = "/Users/robbin/WorkBuddy/20260428102311/relay_server/keys/.auth_token"

def load_token() -> str:
    with open(TOKEN_FILE, "r") as f:
        return f.read().strip()

_next_id = 1
def make_id() -> int:
    global _next_id
    id_ = _next_id
    _next_id += 1
    return id_

# 收集所有收到的事件
events = []

async def recv_response(ws, expected_id, timeout=15):
    """接收消息，区分事件和响应"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, remaining))
        msg = json.loads(raw)
        
        if "id" in msg and msg["id"] == expected_id:
            return msg
        elif "method" in msg:
            events.append(msg)
            print(f"    [事件] {msg['method']}")
        else:
            events.append(msg)
    
    return None


async def test_cdp_connection():
    token = load_token()
    encoded_token = quote(token, safe="")
    ws_url = f"ws://{RELAY_HOST}:{RELAY_PORT}/cdp?token={encoded_token}"

    print(f"🔗 连接: {ws_url[:50]}...")

    async with websockets.connect(ws_url) as ws:
        print("✅ CDP WebSocket 连接成功!\n")

        # ---- 测试 1: Browser.getVersion ----
        print("=" * 55)
        print("  测试 1: Browser.getVersion (伪命令)")
        print("=" * 55)
        id_ = make_id()
        await ws.send(json.dumps({"id": id_, "method": "Browser.getVersion"}))
        resp = await recv_response(ws, id_)
        product = resp.get("result", {}).get("product", "")
        print(f"  ✅ product = {product}\n")

        # ---- 测试 2: Target.getTargets ----
        print("=" * 55)
        print("  测试 2: Target.getTargets (伪命令)")
        print("=" * 55)
        id_ = make_id()
        await ws.send(json.dumps({"id": id_, "method": "Target.getTargets"}))
        resp = await recv_response(ws, id_)
        targets = resp.get("result", {}).get("targetInfos", [])
        print(f"  发现 {len(targets)} 个标签页:")
        for i, t in enumerate(targets):
            print(f"    [{i+1}] {t.get('title', 'N/A')[:50]}")
            print(f"        targetId={t.get('targetId')}, url={t.get('url', '')[:70]}")
        print(f"  ✅ 通过\n")

        if not targets:
            print("⚠️ 没有可用的 targets，测试结束")
            return

        # ---- 测试 3: Target.attachToTarget ----
        target_id = targets[0]["targetId"]
        print("=" * 55)
        print(f"  测试 3: Target.attachToTarget → {target_id}")
        print("=" * 55)
        id_ = make_id()
        await ws.send(json.dumps({
            "id": id_,
            "method": "Target.attachToTarget",
            "params": {"targetId": target_id, "flatten": True},
        }))
        resp = await recv_response(ws, id_, timeout=15)
        
        # 响应可能是命令结果，也可能是空（attach 通过事件返回）
        session_id = None
        if resp and "result" in resp:
            session_id = resp["result"].get("sessionId")
        
        # 也可能从事件中获取
        if not session_id:
            for evt in events:
                if evt.get("method") == "Target.attachedToTarget":
                    session_id = evt.get("params", {}).get("sessionId")
                    real_target_id = evt.get("params", {}).get("targetInfo", {}).get("targetId", "")
                    print(f"    事件中获得: sessionId={session_id}")
                    if real_target_id != target_id:
                        print(f"    targetId 更新: {target_id} → {real_target_id}")
                        target_id = real_target_id
                    break
        
        if session_id:
            print(f"  ✅ attach 成功! sessionId={session_id}\n")
        else:
            print(f"  ⚠️ 未能获取 sessionId，尝试继续...\n")
            # 从 events 中取最新的 sessionId
            if events:
                for evt in reversed(events):
                    if evt.get("method") == "Target.attachedToTarget":
                        session_id = evt.get("params", {}).get("sessionId")
                        target_id = evt.get("params", {}).get("targetInfo", {}).get("targetId", target_id)
                        break

        # ---- 测试 4: Page.enable ----
        if session_id:
            print("=" * 55)
            print("  测试 4: Page.enable (通过 session)")
            print("=" * 55)
            id_ = make_id()
            await ws.send(json.dumps({
                "id": id_,
                "method": "Page.enable",
                "sessionId": session_id,
            }))
            resp = await recv_response(ws, id_, timeout=10)
            if resp and "result" in resp:
                print(f"  ✅ Page.enable 成功\n")
            elif resp and "error" in resp:
                print(f"  ⚠️ Page.enable 错误: {resp['error']}\n")
            else:
                print(f"  ⚠️ Page.enable 无响应\n")

            # ---- 测试 5: Page.navigate ----
            print("=" * 55)
            print("  测试 5: Page.navigate → https://www.baidu.com")
            print("=" * 55)
            id_ = make_id()
            await ws.send(json.dumps({
                "id": id_,
                "method": "Page.navigate",
                "params": {"url": "https://www.baidu.com"},
                "sessionId": session_id,
            }))
            resp = await recv_response(ws, id_, timeout=15)
            if resp and "result" in resp:
                frame_id = resp["result"].get("frameId", "N/A")
                print(f"  ✅ 导航成功! frameId={frame_id}")
                print(f"     浏览器应该已跳转到百度!\n")
            elif resp and "error" in resp:
                print(f"  ⚠️ 导航错误: {resp['error']}\n")
            else:
                print(f"  ⚠️ 导航无响应\n")

            # ---- 测试 6: Runtime.evaluate ----
            print("=" * 55)
            print("  测试 6: Runtime.evaluate → document.title")
            print("=" * 55)
            id_ = make_id()
            await ws.send(json.dumps({
                "id": id_,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.title"},
                "sessionId": session_id,
            }))
            resp = await recv_response(ws, id_, timeout=10)
            if resp and "result" in resp:
                result_val = resp["result"].get("result", {})
                title = result_val.get("value", "N/A")
                print(f"  ✅ document.title = \"{title}\"\n")
            elif resp and "error" in resp:
                print(f"  ⚠️ 错误: {resp['error']}\n")

        # ---- 总结 ----
        print("=" * 55)
        print("  🎉 CDP 命令转发测试完成!")
        print("=" * 55)
        print(f"  收到事件数: {len(events)}")
        for evt in events[:10]:
            print(f"    - {evt.get('method', evt.get('id', 'unknown'))}")


if __name__ == "__main__":
    asyncio.run(test_cdp_connection())
