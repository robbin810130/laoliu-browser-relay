# 方案C 深度可行性验证报告

> 基于 Accio Desktop 源码逆向 + Extension 完整审计 + Relay Server 实现提取

## 最终结论：✅ 方案C 可以完整复制，且存在第三条路径

---

## 一、重大新发现

### 🔥 发现1：RSA 私钥可从 Accio Desktop 提取

Accio Desktop 的 RSA 私钥存储在 `app.asar` 中的 minified JS 里，使用简单的 XOR 混淆：

```
混淆方式：Base64编码的数据 XOR "PhoenixRelayKeyGuard2024"（循环）
存储位置：/Applications/Accio.app/Contents/Resources/app.asar → out/main/index.js
```

解密后得到 PKCS#8 格式的 RSA-2048 私钥，与 Extension 硬编码的公钥匹配。

**意义**：这意味着方案C现在有**三条路径**可选（见下文）。

### 🔥 发现2：Accio Desktop Relay Server 完整实现已提取

从 `app.asar` 中成功提取了 RelayServer 类的完整实现（minified），核心逻辑包括：

| 模块 | Accio 实现 | 关键细节 |
|------|-----------|---------|
| HTTP Server | `http.createServer` | 监听 127.0.0.1:9236，处理 HEAD/GET/OPTIONS |
| WS /extension | `new WebSocketServer({noServer: true})` | Extension 连接端点，origin 校验 |
| WS /cdp | `new WebSocketServer({noServer: true})` | Agent CDP 连接端点，authToken 认证 |
| 握手 | 5秒超时等待 Extension.hello | protocolVersion !== 1 → 4001 关闭 |
| 加密 | Node.js `crypto.privateDecrypt` + `createCipheriv('aes-256-gcm')` | AES-256-GCM，IV=12字节，AuthTag=16字节 |
| Ping | `setInterval` 每 5秒 | Server → Extension `{method:"ping"}` |
| 消息路由 | `onExtensionMessage` | 处理 forwardCDPEvent、命令响应、tab 事件 |
| CDP 命令转发 | `sendToExtension(method, params, sessionId)` | 带 `id`、`ts`、`method: "forwardCDPCommand"` |
| 断连宽限 | 8秒 | EXTENSION_RECONNECT_GRACE_MS = 8000 |
| 版本不匹配 | 自动请求 Extension reload | `Extension.helloAck { action: "reload", reloadTargetKey }` |

### 🔥 发现3：加密并非强制——Desktop 端有降级逻辑

Desktop Relay 的握手代码揭示了一个关键细节：

```javascript
// 如果解密 session key 失败，Desktop 不会断连！
// 而是降级为明文模式
try {
    this._sessionKey = decryptSessionKey(encryptedSessionKey)
    this._encryptionActive = true
} catch (err) {
    this._encryptionErrors++
    this._lastEncryptionError = `handshake: ${err.message}`
    // ⚠️ 不断连！继续运行，只是不加密
    this._sessionKey = null
    this._encryptionActive = false
}

// helloAck 只在有加密时才加 encrypted: true
if (this._encryptionActive) u.encrypted = true
```

**但 Extension 侧的代码是：**
```javascript
if (p.encrypted === true) {
    activateEncryption()
} else {
    disconnect()  // ⚠️ Extension 会断连！
}
```

所以实际情况是：
- Desktop 可以接受不加密（降级），但 **Extension 不接受**
- 要让 Extension 不断连，helloAck **必须** 包含 `encrypted: true`

### 🔥 发现4：Desktop 有完整的 CDP 命令路由

Relay Server 不只是消息路由器，它还实现了部分 CDP 命令的本地处理：

| 命令 | 响应 | 说明 |
|------|------|------|
| `Browser.getVersion` | `{protocolVersion: "1.3", product: "Phoenix-Extension-Relay"}` | 伪造浏览器信息 |
| `Target.getTargets` | 从 `connectedTargets` 过滤 physical | 返回已连接标签页 |
| `Target.getTargetInfo` | 查找 sessionId/targetId | 返回标签页信息 |
| `Target.getBrowserContexts` | `{browserContextIds: []}` | 空的浏览器上下文 |
| 多个 enable 命令 | `{}` | Browser.setDownloadBehavior/Page.enable/Log.enable 等 |

这意味着自建 Relay 也需要实现这些"伪 CDP 命令"，否则 Agent 端可能报错。

---

## 二、方案C 的三条路径

### 路径 C-Prime：零修改 Extension + 提取的私钥（🚀 最快上线）

| 维度 | 详情 |
|------|------|
| **Extension** | 完全不修改，直接用 Accio 原版 |
| **Relay Server** | Python FastAPI，使用提取的 RSA 私钥解密 session key |
| **优点** | 零开发量的 Extension 改动，Accio 更新后可能自动兼容 |
| **缺点** | 依赖 Accio 的私钥（法律灰色地带）；Accio 更新可能更换密钥对 |
| **工作量** | 1-2天（只需实现 Relay Server） |

### 路径 C-Fork：Fork Extension + 自有密钥对（🛡️ 最稳健）

| 维度 | 详情 |
|------|------|
| **Extension** | Fork 后替换 RSA 公钥 + 改品牌名 + 替换图标 |
| **Relay Server** | Python FastAPI，使用自己的 RSA 私钥 |
| **优点** | 完全自主，无法律风险，可自由修改 |
| **缺点** | 需要维护 Fork 版本；Extension 改动稍多 |
| **工作量** | 2-3天 |

### 路径 C-Skip：Fork Extension + 跳过加密（⚡ 最简单）

| 维度 | 详情 |
|------|------|
| **Extension** | Fork 后修改 connection.js，移除加密强制检查 |
| **Relay Server** | Python FastAPI，纯明文 WebSocket |
| **优点** | 实现最简单，不涉及加密逻辑 |
| **缺点** | 本地通信无加密（仅限本机使用无影响） |
| **工作量** | 1天 |

---

## 三、Relay Server 必须实现的完整协议规范

### 3.1 WebSocket 端点

| 端点 | 路径 | 用途 | 认证 |
|------|------|------|------|
| Extension WS | `/extension` | Chrome Extension 连接 | origin 必须是 `chrome-extension://` |
| Agent CDP WS | `/cdp` | Agent/Playwright 连接 | HTTP Header `Authorization: Bearer <authToken>` |

### 3.2 HTTP 端点

| 方法 | 路径 | 响应 | 说明 |
|------|------|------|------|
| HEAD | `/` | 200 OK | Extension 预检（连接前探测） |
| GET | `/` | 200 "OK" | 健康检查 |
| GET | `/status` | 200 JSON | 连接状态 |
| GET | `/json/list` | 200 JSON | 标签页列表 |
| GET/PUT | `/json/close/<targetId>` | 200 OK | 关闭标签页 |
| OPTIONS | 任意 | 204 + CORS headers | CORS 预检 |

### 3.3 握手协议（Extension 连接后 5 秒内必须完成）

```
Extension → Relay:  { method: "Extension.hello", params: { protocolVersion: 1, extensionVersion: "x.y.z", encryptedSessionKey: "<base64>" } }
Relay → Extension:  { method: "Extension.helloAck", params: { status: "ok", encrypted: true } }
```

**关键**：`encrypted: true` 是必须的，否则 Extension 断连。

### 3.4 加密协议

- 密钥交换：Extension 用 RSA-2048-OAEP/SHA-256 加密 AES-256 会话密钥
- 传输格式：`"E:" + base64(IV[12] + ciphertext + authTag[16])`
- Python 实现：`cryptography` 库的 `AES-GCM`

### 3.5 心跳协议

- Relay → Extension：每 5 秒发送 `{ method: "ping" }`
- Extension → Relay：回复 `{ method: "pong" }`
- Extension 侧还有 30 秒的 alarm 心跳

### 3.6 CDP 命令转发格式

```json
// Relay → Extension（命令请求）
{ "id": 42, "ts": 1709847600000, "method": "forwardCDPCommand", "params": { "method": "Page.navigate", "sessionId": "cb-tab-1-42", "params": { "url": "https://example.com" } } }

// Extension → Relay（命令响应-成功）
{ "id": 42, "result": { "frameId": "..." } }

// Extension → Relay（命令响应-失败）
{ "id": 42, "error": "Error message string" }

// Extension → Relay（CDP 事件通知）
{ "method": "forwardCDPEvent", "params": { "sessionId": "cb-tab-1-42", "method": "Page.loadEventFired", "params": { ... } } }
```

### 3.7 特殊 Extension 事件（必须正确处理）

| 事件 | 处理逻辑 |
|------|---------|
| `Extension.tabDiscovered` | 记录到 connectedTargets，sessionId/targetId 映射 |
| `Extension.tabUpdated` | 更新 connectedTargets 中的 URL/标题 |
| `Extension.tabRemoved` | 从 connectedTargets 删除 |
| `Target.attachedToTarget` | 标记为 physical=true，更新 targetId |
| `Target.detachedFromTarget` | 从 connectedTargets 删除，广播给 CDP 客户端 |

### 3.8 必须实现的伪 CDP 命令

| 命令 | 返回值 |
|------|--------|
| `Browser.getVersion` | `{ protocolVersion: "1.3", product: "Custom-Relay" }` |
| `Target.getTargets` | `{ targetInfos: [...physicalTargets] }` |
| `Target.getBrowserContexts` | `{ browserContextIds: [] }` |
| `Target.setAutoAttach` | `{}` |
| `Target.setDiscoverTargets` | `{}` |
| `Page.enable` / `Log.enable` / `Inspector.enable` / `Performance.enable` | `{}` |

### 3.9 消息过期机制

- Relay 发送的 `forwardCDPCommand` 可包含 `ts` 字段（Unix ms 时间戳）
- Extension 检查消息年龄，超过 130 秒的命令会被丢弃并返回错误
- **建议**：自建 Relay 必须在每个命令中包含 `ts: Date.now()`

### 3.10 断连宽限期

- Extension 断连后，Relay 有 8 秒宽限期等待重连
- 宽限期内：Extension 可重新连接，不清理状态
- 宽限期后：清理 connectedTargets，关闭所有 CDP 客户端

---

## 四、Relay Server Python 实现方案

### 技术选型

| 组件 | 推荐 | 原因 |
|------|------|------|
| Web 框架 | FastAPI | 异步、WebSocket 原生支持 |
| WebSocket | fastapi.WebSocket | 与 FastAPI 无缝集成 |
| 加密 | cryptography (pyca) | RSA-OAEP + AES-256-GCM 完整支持 |
| HTTP | uvicorn | ASGI 服务器 |

### 核心模块架构

```
relay_server/
├── main.py              # FastAPI app + uvicorn 启动
├── ws_extension.py      # /extension WebSocket 端点
├── ws_cdp.py            # /cdp WebSocket 端点
├── handshake.py         # Extension.hello/helloAck 握手处理
├── crypto.py            # RSA 解密 + AES-256-GCM 加解密
├── router.py            # CDP 命令路由（forwardCDPCommand/Event）
├── target_manager.py    # connectedTargets 管理
├── cdp_fakes.py         # 伪 CDP 命令实现
├── config.py            # 端口/密钥/超时配置
└── models.py            # Pydantic 消息模型
```

### 关键实现要点

1. **loopback-only**：HTTP Server 只监听 127.0.0.1
2. **origin 校验**：/extension 只接受 chrome-extension:// 来源
3. **authToken**：启动时生成随机 32 字节 base64url token，/cdp 端点需要此 token
4. **单 Extension 连接**：同一时间只允许一个 Extension WebSocket
5. **命令超时**：Relay → Extension 的命令有超时（默认配置，Accio 用 `cdpCommandMs` / `cdpCommandLongMs`）
6. **消息 ID 映射**：CDP 客户端的命令 ID 与 Extension 命令 ID 需要映射

---

## 五、风险矩阵（更新版）

| 风险 | 严重度 | 概率 | 缓解措施 |
|------|--------|------|---------|
| Accio 更新 Extension 协议 | 高 | 低 | C-Fork 路径独立维护；C-Prime 路径锁定版本 |
| RSA 私钥提取的法律风险 | 中 | — | C-Fork 使用自有密钥对 |
| MV3 Service Worker 生命周期 | 低 | 低 | Extension 已有完善的 alarm 机制 |
| AES-256-GCM 实现兼容性 | 低 | 低 | Python cryptography 库与 WebCrypto 完全兼容 |
| CDP 事件风暴导致性能问题 | 低 | 中 | Relay 可添加事件过滤/限流 |
| 多 Agent 并发冲突 | 中 | 中 | 初始版本限制单 Agent 连接 |

---

## 六、推荐实施路径

### 🏆 推荐：路径 C-Fork（自有密钥对）

理由：
1. **法律安全**：不使用 Accio 的私钥，完全自主
2. **长期可维护**：独立于 Accio 更新
3. **可扩展**：可自由添加 MCP 适配、权限控制等
4. **工作量可控**：2-3天完成核心功能

### 实施步骤

1. **Day 1**：Fork Extension + 替换密钥对 + 品牌修改
2. **Day 1-2**：实现 Relay Server 核心（握手+加密+消息路由）
3. **Day 2**：实现伪 CDP 命令 + CDP WebSocket 端点
4. **Day 2-3**：端到端测试 + 接入预留模块
5. **Day 3**：MCP 适配层 + 文档

---

## 七、与上一版审计报告的差异

| 维度 | 上一版结论 | 本次深度验证 |
|------|-----------|-------------|
| Relay Server 角色 | "纯消息管道" | 不完全是——有伪 CDP 命令实现、target 管理 |
| 加密 | "可跳过" | **Extension 不允许跳过**，必须实现加密或修改 Extension |
| 实现难度 | "1-2天" | **2-3天**（需实现伪 CDP 命令 + 更复杂的握手逻辑） |
| 端点 | 只提 /extension | 还有 /cdp、/json/*、/status 等 |
| 心跳 | 简单 ping/pong | Relay 5秒 + Extension 30秒双层心跳 |
| 断连处理 | 未提及 | 8秒宽限期 + 自动重连 + CDP 客户端级联断连 |

**核心结论不变**：方案C 可以完整复制 Accio 的浏览器自动化能力。但实现复杂度比初始评估略高，需要额外处理伪 CDP 命令和双层心跳机制。
