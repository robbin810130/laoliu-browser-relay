# Accio 浏览器自动化能力完整清单 & 方案C覆盖度验证

> 逐模块审计，验证 Fork + 自建 Relay Server 方案能否 100% 复制能力

## 结论：✅ 方案C 可以完整复制所有能力

Extension 本身是**被动的命令执行器**，所有智能逻辑都在 Extension 内部。
Relay Server 只是一个"消息路由器"——它不产生任何浏览器控制逻辑，
只是把 Agent 的 CDP 命令转发给 Extension，再把 Extension 的事件回传给 Agent。

---

## 一、能力全景图（6大模块 30+ 能力点）

### 模块1：CDP 通道（chrome.debugger API）

| # | 能力 | 文件 | 实现位置 | 方案C覆盖 | 说明 |
|---|------|------|---------|-----------|------|
| 1 | debugger attach/detach | debugger-attach.js | Extension | ✅ Fork直接复制 | 代码在Extension侧 |
| 2 | CDP 命令透传 | dispatch.js | Extension | ✅ Fork直接复制 | 任意CDP命令直接转发 |
| 3 | Per-tab 命令队列 | dispatch.js | Extension | ✅ Fork直接复制 | 串行化，MAX_QUEUE_DEPTH=100 |
| 4 | CDP 命令超时 | utils.js | Extension | ✅ Fork直接复制 | 30秒超时 |
| 5 | Runtime.enable 特殊处理 | dispatch.js | Extension | ✅ Fork直接复制 | 先disable再enable+延迟 |
| 6 | Child session 跟踪 | manager.js | Extension | ✅ Fork直接复制 | iframe/worker的session映射 |
| 7 | Target.* 命令 | target-ops.js | Extension | ✅ Fork直接复制 | 创建/关闭/激活标签页 |

### 模块2：Content Script 通道（chrome.scripting API）

| # | 能力 | 文件 | 实现位置 | 方案C覆盖 | 说明 |
|---|------|------|---------|-----------|------|
| 8 | 视口信息获取 | extension-ops.js | Extension | ✅ Fork直接复制 | 尺寸/DPR/缩放/滚动位置 |
| 9 | 缩放控制 | extension-ops.js | Extension | ✅ Fork直接复制 | chrome.tabs.setZoom |
| 10 | 视口截图 | extension-ops.js | Extension | ✅ Fork直接复制 | Page.captureScreenshot + DPR适配 |
| 11 | 页面内容提取（HTML→MD） | extension-ops.js | Extension | ✅ Fork直接复制 | DOM walker → Markdown |
| 12 | 3x4网格可见性检测 | extension-ops.js | Extension | ✅ Fork直接复制 | elementFromPoint多点采样，30%阈值 |
| 13 | 交互元素标记 | extension-ops.js | Extension | ✅ Fork直接复制 | data-accio-idx标注 |
| 14 | DOM点击（单/双/右键） | extension-ops.js | Extension | ✅ Fork直接复制 | 完整鼠标事件序列 |
| 15 | DOM输入（native setter） | extension-ops.js | Extension | ✅ Fork直接复制 | 绕过React/Vue拦截 |
| 16 | 点击涟漪动画 | extension-ops.js | Extension | ✅ Fork直接复制 | CSS动画反馈 |
| 17 | 键盘事件模拟 | press-key.js | Extension | ✅ Fork直接复制 | 支持 modifier combos |
| 18 | 滚动（方向/容器/到底） | scroll.js | Extension | ✅ Fork直接复制 | 自动查找可滚动容器 |
| 19 | 关键词搜索 | find-keyword.js | Extension | ✅ Fork直接复制 | 页内搜索+上下文 |
| 20 | 鼠标悬停 | move-mouse.js | Extension | ✅ Fork直接复制 | mouseover/mousemove事件 |
| 21 | 高亮截图标注 | highlight-screenshot.js | Extension | ✅ Fork直接复制 | OffscreenCanvas渲染 |

### 模块3：Shadow DOM 支持

| # | 能力 | 文件 | 实现位置 | 方案C覆盖 | 说明 |
|---|------|------|---------|-----------|------|
| 22 | deepQuery（穿透Shadow DOM） | extension-ops.js | Extension | ✅ Fork直接复制 | 递归查找所有shadowRoot |
| 23 | deepElementFromPoint | extension-ops.js | Extension | ✅ Fork直接复制 | shadowRoot.elementFromPoint |

### 模块4：Rich Text / 富文本编辑器

| # | 能力 | 文件 | 实现位置 | 方案C覆盖 | 说明 |
|---|------|------|---------|-----------|------|
| 24 | DraftEditor检测+输入 | input-enhanced.js | Extension | ✅ Fork直接复制 | execCommand("delete"+"insertText") |
| 25 | Slate编辑器检测+输入 | input-enhanced.js | Extension | ✅ Fork直接复制 | data-slate-editor检测 |
| 26 | ProseMirror/contentEditable | input-enhanced.js | Extension | ✅ Fork直接复制 | execCommand → textContent降级 |
| 27 | Readability评分提取 | extract-readability.js | Extension | ✅ Fork直接复制 | 双路径提取+评分回退 |

### 模块5：CDP 事件拦截（自动处理）

| # | 能力 | 文件 | 实现位置 | 方案C覆盖 | 说明 |
|---|------|------|---------|-----------|------|
| 28 | 对话框自动接受 | dialog.js | Extension | ✅ Fork直接复制 | alert/confirm/prompt/beforeunload |
| 29 | 证书错误自动跳过 | security.js | Extension | ✅ Fork直接复制 | Security.handleCertificateError |
| 30 | Debugger.paused自动恢复 | debugger-domain.js | Extension | ✅ Fork直接复制 | 防止页面冻结 |
| 31 | 页面生命周期事件 | page-lifecycle.js | Extension | ✅ Fork直接复制 | 加载/导航/下载/文件选择 |
| 32 | 网络请求事件 | network.js | Extension | ✅ Fork直接复制 | request/response/lifecycle |
| 33 | JS异常/控制台事件 | runtime.js | Extension | ✅ Fork直接复制 | exception/console/context |
| 34 | Target生命周期 | target.js | Extension | ✅ Fork直接复制 | session attach/detach/crash |
| 35 | Inspector断连 | inspector.js | Extension | ✅ Fork直接复制 | detach/crash/reload |
| 36 | Fetch拦截（relay控制） | fetch.js | Extension | ✅ Fork直接复制 | requestPaused/authRequired |
| 37 | Input拖拽拦截 | input.js | Extension | ✅ Fork直接复制 | dragIntercepted |

### 模块6：Tab管理 & 连接管理

| # | 能力 | 文件 | 实现位置 | 方案C覆盖 | 说明 |
|---|------|------|---------|-----------|------|
| 38 | Lazy Attach架构 | manager.js | Extension | ✅ Fork直接复制 | virtual→attaching→connected |
| 39 | 标签页发现 | manager.js | Extension | ✅ Fork直接复制 | chrome.tabs.query |
| 40 | Agent标签页追踪 | manager.js | Extension | ✅ Fork直接复制 | 区分用户/agent/retained |
| 41 | Tab Group管理 | agent-group.js | Extension | ✅ Fork直接复制 | Chrome标签组 |
| 42 | Spinner动画 | session-indicators.js | Extension | ✅ Fork直接复制 | braille字符动画 |
| 43 | 空闲标签页自动detach | session-indicators.js | Extension | ✅ Fork直接复制 | 5分钟无命令自动detach |
| 44 | 用户取消记住 | manager.js | Extension | ✅ Fork直接复制 | cancelled_by_user持久化 |
| 45 | 多端口竞速连接 | connection.js | Extension | ✅ Fork直接复制 | Promise.any竞速 |

### 预留模块（已实现但未启用）

| # | 能力 | 文件 | 状态 | 方案C覆盖 |
|---|------|------|------|-----------|
| 46 | 操作遮罩（防用户干扰） | action-mask.js | 未接入dispatch | ✅ 可在自建Relay中启用 |
| 47 | 页面就绪等待 | wait-ready.js | 未接入dispatch | ✅ 可在自建Relay中启用 |
| 48 | 增强版内容提取 | extract-readability.js | 未接入dispatch | ✅ 可在自建Relay中启用 |
| 49 | 增强版输入 | input-enhanced.js | 未接入dispatch | ✅ 可在自建Relay中启用 |
| 50 | Service Worker心跳 | keepalive.js | 未接入dispatch | ✅ 可在自建Relay中启用 |

---

## 二、关键发现

### 🔑 发现1：Relay Server 是纯粹的"消息管道"

Relay Server 在整个架构中**不执行任何浏览器控制逻辑**。它的唯一职责是：
1. 接收 Extension 的 WebSocket 连接
2. 转发 Agent → Extension 的 CDP 命令
3. 转发 Extension → Agent 的 CDP 事件
4. RSA 私钥解密 + AES 消息加解密

**这意味着：自建 Relay Server 不需要复制任何"智能逻辑"，只需要实现消息路由和加密。**

### 🔑 发现2：Extension 内部有4个"预留"高级能力

input-enhanced.js、extract-readability.js、action-mask.js、wait-ready.js 这4个模块
已经完整实现但**没有接入 dispatch.js**。Accio Desktop 当前也没使用它们。

在方案C中，我们可以直接把它们接入 dispatch.js，获得比 Accio 更强的能力！

### 🔑 发现3：加密是可选的简化点

Extension 的 crypto.js 实现了 RSA+AES 加密。但仔细看 connection.js 第596行：
```
if (p.encrypted !== true) {
  log.warn('Extension.helloAck: server does not support encryption — disconnecting')
```
**Accio 要求加密，否则断连。** 但在自建方案中，我们可以：
- 方案C-a：完整复制加密（安全）
- 方案C-b：修改 Extension 跳过加密要求（简单，本地使用足够）

### 🔑 发现4：协议版本是关键兼容点

Extension.hello 发送 `protocolVersion: 1`，Relay Server 必须返回匹配的版本。
这是唯一可能导致不兼容的地方——但自建方案中双方都由我们控制，不存在版本不匹配问题。

---

## 三、方案C 需要改动的具体清单

### Extension 侧改动（最小化）

| 改动 | 文件 | 难度 | 说明 |
|------|------|------|------|
| 替换RSA公钥 | crypto.js | ⭐ | openssl生成新密钥对 |
| 修改品牌名称 | manifest.json, agent-group.js, session-indicators.js, action-mask.js | ⭐ | 批量替换"Accio" |
| 替换图标 | icons/ | ⭐ | 自己的图标 |
| (可选)接入预留模块 | dispatch.js | ⭐⭐ | 添加Extension.inputEnhanced等路由 |
| (可选)跳过加密 | connection.js | ⭐ | 移除加密强制检查 |

### Relay Server 侧（需新建）

| 模块 | 功能 | 难度 | 说明 |
|------|------|------|------|
| WebSocket Server | ws://127.0.0.1:9236/extension | ⭐⭐ | FastAPI + WebSocket |
| 握手协议 | Extension.hello/helloAck | ⭐⭐ | 版本号+加密协商 |
| 消息路由 | forwardCDPCommand/forwardCDPEvent | ⭐⭐ | 双向JSON转发 |
| 加密层 | RSA解密+AES加解密 | ⭐⭐⭐ | cryptography库 |
| HTTP API | Agent → Relay 的 REST 接口 | ⭐⭐ | POST /cdp-command |
| 心跳 | ping/pong | ⭐ | 定时发送 |
| 预检 | HEAD / | ⭐ | 200 OK即可 |

---

## 四、风险点

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| Accio 更新 Extension 导致协议变更 | 低 | 自建后独立维护，不跟随Accio更新 |
| MV3 Service Worker 生命周期限制 | 低 | Extension 已有完善的alarm+keepalive机制 |
| 加密实现bug | 中 | 可先跳过加密，本地使用无需加密 |
| Chrome API 变更 | 低 | chrome.debugger/scripting 是稳定API |

---

## 五、额外增强机会

方案C 不仅100%复制能力，还可以**超越Accio**：

1. **启用预留模块**：input-enhanced + extract-readability + action-mask + wait-ready
2. **MCP协议适配**：让 Relay Server 直接暴露 MCP tools，任何 MCP 客户端都能用
3. **多Agent并发**：Relay Server 可以同时服务多个 Agent 连接
4. **录制回放**：在 Relay 层记录所有 CDP 命令，实现操作回放
5. **权限控制**：限制 Agent 可执行的 CDP 域，增强安全性
