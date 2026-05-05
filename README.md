# LaoLiu Browser Relay

> 🔥 通过 MCP 协议控制 Chrome 浏览器 — 自建 Relay Server + Chrome Extension，端到端加密

**LaoLiu Browser Relay** 让任何支持 MCP（Model Context Protocol）的 AI Agent 都能控制 Chrome 浏览器：导航网页、执行 JS、截图、点击、输入文字，全部通过端到端加密通道完成。

## 架构

```
┌──────────────┐    stdio/MCP     ┌──────────────────┐    WebSocket     ┌────────────────────┐
│  AI Agent    │◄────────────────►│  MCP Server      │◄────────────────►│  Relay Server      │
│  (Claude/    │   (browser_*)    │  (Node.js)       │   /cdp?token=    │  (Python FastAPI)  │
│   Cursor/    │                  │  laoliu-mcp/     │                  │  relay_server/     │
│   Cline...)  │                  │                  │                  │                    │
└──────────────┘                  └──────────────────┘                  └────────┬───────────┘
                                                                                 │ WebSocket
                                                                                 │ /extension
                                                                       ┌─────────▼──────────┐
                                                                       │  Chrome Extension   │
                                                                       │  laoliu-browser-    │
                                                                       │  relay/             │
                                                                       │  (端到端加密)        │
                                                                       └────────────────────┘
```

**核心原理：**
1. **MCP Server**（Node.js）通过 stdio 与 AI Agent 通信，提供 `browser_*` 系列工具
2. **Relay Server**（Python FastAPI）作为中间人，管理 WebSocket 连接和消息路由
3. **Chrome Extension** 注入到浏览器中，执行实际 CDP 命令
4. 全链路 **AES-256-GCM 端到端加密**，密钥通过 RSA-OAEP 交换

## 功能

| 工具 | 说明 |
|------|------|
| `browser_status` | 检查连接状态、Extension 是否在线 |
| `browser_navigate` | 导航到指定 URL |
| `browser_evaluate` | 执行 JavaScript 表达式 |
| `browser_screenshot` | 页面截图（返回 base64 图片） |
| `browser_click` | 点击 CSS 选择器指定的元素 |
| `browser_type` | 在输入框中输入文本 |
| `browser_list_tabs` | 列出所有标签页 |
| `browser_cdp` | 发送原始 CDP 命令（高级） |

## 快速开始

### 前置条件

- **Python 3.10+**（Relay Server 依赖）
- **Node.js 18+**（MCP Server 依赖）
- **Chrome 浏览器**
- **pip 依赖**：`fastapi`, `uvicorn`, `cryptography`, `websockets`

### 第 1 步：克隆项目

```bash
git clone https://github.com/robbin810130/laoliu-browser-relay.git
cd laoliu-browser-relay
```

### 第 2 步：安装依赖

```bash
# Python 依赖
pip install -r relay_server/requirements.txt

# Node.js 依赖
cd laoliu-mcp && npm install && cd ..
```

### 第 3 步：生成密钥

首次使用需要生成 RSA 密钥对（用于端到端加密）：

```bash
python3 relay_server/generate_keys.py
```

这会在 `relay_server/keys/` 下生成 `private_key.pem`、`public_key.pem`、`public_key.der`。

### 第 4 步：安装 Chrome Extension

1. 打开 Chrome，访问 `chrome://extensions/`
2. 开启右上角 **开发者模式**
3. 点击 **加载已解压的扩展程序**
4. 选择 `laoliu-browser-relay/` 目录（即项目中的 Extension 子目录）
5. Extension 图标出现在工具栏，显示 🔴 Disconnected（正常，Relay 还没启动）

### 第 5 步：配置你的 AI Agent

根据你使用的 Agent，添加 MCP 配置：

#### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "laoliu-browser": {
      "type": "stdio",
      "command": "node",
      "args": ["/ABSOLUTE/PATH/TO/laoliu-browser-relay/laoliu-mcp/index.js"]
    }
  }
}
```

#### Cursor

在项目根目录创建 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "laoliu-browser": {
      "type": "stdio",
      "command": "node",
      "args": ["/ABSOLUTE/PATH/TO/laoliu-browser-relay/laoliu-mcp/index.js"]
    }
  }
}
```

#### Cline / 其他 MCP 客户端

参考上述格式，在对应配置文件中添加 `laoliu-browser` MCP Server。

#### WorkBuddy

编辑 `~/.workbuddy/mcp.json`：

```json
{
  "mcpServers": {
    "laoliu-browser": {
      "type": "stdio",
      "command": "node",
      "args": ["/ABSOLUTE/PATH/TO/laoliu-browser-relay/laoliu-mcp/index.js"]
    }
  }
}
```

### 第 6 步：开始使用

1. 启动你的 AI Agent
2. Extension 图标会变为 🟢 Connected（MCP Server 会自动启动 Relay Server）
3. 对 Agent 说："打开 https://example.com" 或 "帮我截个图"

## 环境变量

所有环境变量都是**可选的**，有合理的默认值：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PHOENIX_PROJECT_DIR` | 自动推导 (`../`) | 项目根目录 |
| `PHOENIX_RELAY_URL` | `http://127.0.0.1:9236` | Relay Server URL |
| `PHOENIX_RELAY_TOKEN` | 自动从 `keys/.auth_token` 读取 | 认证 Token |
| `PHOENIX_PYTHON` | 自动查找 `python3` | Python 可执行文件路径 |
| `PHOENIX_AUTO_START` | `true` | 是否自动启动 Relay Server |

## 手动启动（调试用）

```bash
# 启动 Relay Server
python3 relay_server/start.sh

# 或直接用 Python
cd relay_server && python3 -m relay_server.main
```

## 项目结构

```
laoliu-browser-relay/
├── relay_server/              # Python FastAPI — WebSocket Relay
│   ├── main.py                #   FastAPI app + 端点注册
│   ├── config.py              #   配置（端口/超时/加密参数）
│   ├── crypto.py              #   RSA-OAEP + AES-256-GCM 加密
│   ├── ws_extension.py        #   Extension WebSocket 处理
│   ├── ws_cdp.py              #   CDP WebSocket 处理
│   ├── router.py              #   CDP 消息路由
│   ├── target_manager.py      #   标签页管理
│   ├── cdp_fakes.py           #   伪 CDP 命令（Browser.getVersion 等）
│   ├── generate_keys.py       #   RSA 密钥对生成脚本
│   ├── requirements.txt       #   Python 依赖
│   └── start.sh               #   启动脚本
├── laoliu-mcp/               # Node.js — MCP Server
│   ├── index.js               #   MCP Server 主程序（8 个工具）
│   └── package.json           #   Node.js 依赖
├── laoliu-browser-relay/      # Chrome Extension│   ├── manifest.json          #   扩展清单
│   ├── background.js          #   Service Worker（WebSocket + 加密）
│   ├── lib/                   #   CDP 事件处理 / 内容脚本
│   ├── pages/                 #   Popup / Options / Install 页面
│   └── icons/                 #   老六图标 六
└── README.md
```

## 安全说明

- **端到端加密**：Relay Server 与 Extension 之间所有通信都通过 AES-256-GCM 加密
- **RSA 密钥交换**：Session key 通过 RSA-OAEP/SHA-256 安全交换
- **本地监听**：Relay Server 只监听 `127.0.0.1`，不暴露到公网
- **Token 认证**：CDP WebSocket 连接需要 auth token
- **密钥不提交**：`keys/` 目录在 `.gitignore` 中，密钥文件不会进入版本控制

## 常见问题

**Q: Extension 显示 🔴 Disconnected？**
- 确认 Relay Server 已启动（MCP Server 会自动启动）
- 检查端口 9236 是否被占用：`lsof -i :9236`

**Q: 启动时报 "RSA 私钥不存在"？**
- 运行 `python3 relay_server/generate_keys.py` 生成密钥

**Q: macOS 上 Python 找不到？**
- 设置环境变量：`export PHOENIX_PYTHON=/opt/homebrew/bin/python3`

**Q: Windows 怎么用？**
- 安装 Python 和 Node.js
- MCP 配置中 `command` 改为 `node` 的完整路径
- Extension 安装方式相同（`chrome://extensions/` → 加载已解压）

## 致谢

本项目从 [Accio](https://github.com/anthropics/accio) Fork 了 Chrome Extension 部分代码，并重写了 Relay Server 和 MCP 适配层。

## License

MIT
