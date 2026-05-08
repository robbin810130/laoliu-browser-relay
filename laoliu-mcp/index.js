#!/usr/bin/env node
/**
 * LaoLiu Browser Relay — MCP Server (v2 自启动版)
 *
 * 核心改进：
 *   - 自动启动 Relay Server（如果没在运行）
 *   - 自动从 keys/.auth_token 读取最新 token
 *   - 路径全部自动推导（基于 __dirname）
 *   - 依赖自检 + 友好错误提示
 *
 * MCP 配置 (mcp.json) — 只需这一行：
 *   {
 *     "laoliu-browser": {
 *       "type": "stdio",
 *       "command": "node",
 *       "args": ["/ABSOLUTE/PATH/TO/laoliu-mcp/index.js"]
 *     }
 *   }
 *
 * 环境变量（可选覆盖）：
 *   PHOENIX_PROJECT_DIR  — 项目根目录（默认从 index.js 位置推导 ../）
 *   PHOENIX_RELAY_URL    — Relay Server URL（默认 http://127.0.0.1:19236）
 *   PHOENIX_RELAY_TOKEN  — Auth token（默认自动从 keys/.auth_token 读取）
 *   PHOENIX_PYTHON       — Python 可执行文件路径（默认自动查找）
 *   PHOENIX_AUTO_START   — 是否自动启动 Relay Server（默认 true）
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { execSync, spawn } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

// ============================================================
// 路径推导
// ============================================================
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_DIR = process.env.PHOENIX_PROJECT_DIR || path.resolve(__dirname, "..");
const RELAY_SERVER_DIR = path.join(PROJECT_DIR, "relay_server");
const EXTENSION_DIR = path.join(PROJECT_DIR, "laoliu-browser-relay");
const KEYS_DIR = path.join(RELAY_SERVER_DIR, "keys");
const TOKEN_FILE = path.join(KEYS_DIR, ".auth_token");

// ============================================================
// 配置
// ============================================================
const RELAY_URL = process.env.PHOENIX_RELAY_URL || "http://127.0.0.1:19236";
const RELAY_WS_URL = RELAY_URL.replace(/^http/, "ws");
const AUTO_START = process.env.PHOENIX_AUTO_START !== "false"; // 默认 true

// ============================================================
// 日志（输出到 stderr，不干扰 MCP stdio）
// ============================================================
function log(msg) {
  process.stderr.write(`[laoliu-mcp] ${msg}\n`);
}

// ============================================================
// 依赖自检
// ============================================================
function findPython() {
  if (process.env.PHOENIX_PYTHON) return process.env.PHOENIX_PYTHON;

  // 按优先级查找 Python（跨平台通用）
  const candidates = [
    // 项目 venv 优先（确保依赖和密钥路径正确）
    path.join(PROJECT_DIR, ".venv", "bin", "python3"),
    // Windows venv 路径
    path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe"),
    // macOS/Linux relay_server 目录内 venv 备选
    path.join(RELAY_SERVER_DIR, ".venv", "bin", "python3"),
    "python3",
    "python",
    // macOS Homebrew
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    // Linux
    "/usr/bin/python3",
    // Windows (Git Bash / WSL)
    "py",
  ];

  for (const cmd of candidates) {
    try {
      // 绝对路径候选先检查文件是否存在，避免执行不存在的命令
      if (path.isAbsolute(cmd) && !fs.existsSync(cmd)) continue;
      const result = execSync(`${cmd} --version 2>&1`, { encoding: "utf-8", timeout: 5000 });
      if (result.includes("Python 3.")) {
        return cmd;
      }
    } catch {
      // 继续尝试下一个
    }
  }
  return null;
}

function checkDependencies() {
  const issues = [];

  // 检查项目目录
  if (!fs.existsSync(RELAY_SERVER_DIR)) {
    issues.push(`Relay Server 目录不存在: ${RELAY_SERVER_DIR}`);
  }

  if (!fs.existsSync(EXTENSION_DIR)) {
    issues.push(`Extension 目录不存在: ${EXTENSION_DIR}`);
  }

  // 检查 Python
  const python = findPython();
  if (!python) {
    issues.push("未找到 Python 3.12+。请安装 Python 或设置 PHOENIX_PYTHON 环境变量。");
  }

  // 检查 RSA 密钥
  if (!fs.existsSync(path.join(KEYS_DIR, "private_key.pem"))) {
    // 尝试自动生成密钥
    if (python) {
      log("RSA 私钥不存在，尝试自动生成...");
      try {
        const genScript = path.join(RELAY_SERVER_DIR, "generate_keys.py");
        execSync(`${python} "${genScript}"`, { encoding: "utf-8", timeout: 10000 });
        log("RSA 密钥自动生成成功 ✅");
      } catch (genErr) {
        issues.push(`RSA 密钥自动生成失败: ${genErr.message}。请手动运行: python3 ${path.join(RELAY_SERVER_DIR, "generate_keys.py")}`);
      }
    } else {
      issues.push(`RSA 私钥不存在: ${KEYS_DIR}/private_key.pem。请先运行: python3 relay_server/generate_keys.py`);
    }
  }

  return { ok: issues.length === 0, issues, python };
}

// ============================================================
// Token 读取（自动从文件读取最新 token）
// ============================================================
async function readToken() {
  // 1. 优先使用环境变量
  if (process.env.PHOENIX_RELAY_TOKEN) {
    return process.env.PHOENIX_RELAY_TOKEN;
  }

  // 2. 从 keys/.auth_token 读取
  try {
    const token = (await fs.promises.readFile(TOKEN_FILE, "utf-8")).trim();
    if (token) return token;
  } catch {
    // 文件可能还不存在（Relay Server 还没启动过）
  }

  return "";
}

// ============================================================
// Relay Server 自启动
// ============================================================
let relayProcess = null;

async function isRelayRunning() {
  try {
    const resp = await fetch(`${RELAY_URL}/`, { signal: AbortSignal.timeout(2000) });
    return resp.ok;
  } catch {
    return false;
  }
}

async function startRelayServer(pythonCmd) {
  if (relayProcess) return true; // 已经启动了

  log(`启动 Relay Server... (python=${pythonCmd})`);

  const env = {
    ...process.env,
    PYTHONPATH: PROJECT_DIR,
  };

  relayProcess = spawn(pythonCmd, ["-m", "relay_server.main"], {
    cwd: PROJECT_DIR,  // 必须从项目根目录启动，确保 config.py 的 Path(__file__).parent 正确解析密钥路径
    env,
    stdio: ["ignore", "pipe", "pipe"],
    detached: false,
  });

  relayProcess.stdout.on("data", (data) => {
    // 转发 Relay Server 日志到 stderr
    for (const line of data.toString().split("\n")) {
      if (line.trim()) log(`[relay] ${line}`);
    }
  });

  relayProcess.stderr.on("data", (data) => {
    for (const line of data.toString().split("\n")) {
      if (line.trim()) log(`[relay] ${line}`);
    }
  });

  relayProcess.on("exit", (code) => {
    log(`Relay Server 退出 (code=${code})`);
    relayProcess = null;
  });

  // 等待 Relay Server 启动就绪
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 500));
    if (await isRelayRunning()) {
      log("Relay Server 已启动 ✅");
      return true;
    }
  }

  log("Relay Server 启动超时 ❌");
  return false;
}

// ============================================================
// 确保整个链路可用
// ============================================================
let relayEnsured = false;

async function ensureRelay() {
  if (relayEnsured) return true;

  // 检查 Relay Server 是否已在运行
  if (await isRelayRunning()) {
    log("Relay Server 已在运行");
    relayEnsured = true;
    return true;
  }

  // 尝试自动启动
  if (!AUTO_START) {
    log("自动启动已禁用 (PHOENIX_AUTO_START=false)");
    return false;
  }

  const deps = checkDependencies();
  if (!deps.ok) {
    log(`依赖检查失败:\n${deps.issues.map(i => `  - ${i}`).join("\n")}`);
    return false;
  }

  if (!deps.python) {
    log("未找到 Python，无法自动启动 Relay Server");
    return false;
  }

  const started = await startRelayServer(deps.python);
  if (started) {
    relayEnsured = true;
  }
  return started;
}

// ============================================================
// CDP WebSocket 客户端（懒连接）
// ============================================================
let ws = null;
let sessionId = null;
let targetId = null;
let msgId = 1;
let pendingRequests = new Map();

async function ensureConnection() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  // 先确保 Relay Server 可用
  const relayOk = await ensureRelay();
  if (!relayOk) {
    throw new Error(
      "Relay Server 不可用。请确认：\n" +
      "1. Relay Server 已启动（或设置 PHOENIX_AUTO_START=true 自动启动）\n" +
      "2. 端口 19236 未被占用\n" +
      `3. 项目目录正确: ${PROJECT_DIR}`
    );
  }

  // 读取最新 token（每次连接都重新读取，不怕 token 刷新）
  const token = await readToken();
  const encodedToken = encodeURIComponent(token);
  const wsUrl = `${RELAY_WS_URL}/cdp?token=${encodedToken}`;

  return new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl);

    const connectTimeout = setTimeout(() => {
      socket.close();
      reject(new Error("WebSocket 连接超时（5秒）"));
    }, 5000);

    socket.onopen = () => {
      clearTimeout(connectTimeout);
      ws = socket;
      resolve();
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      handleWsMessage(msg);
    };

    socket.onerror = (err) => {
      clearTimeout(connectTimeout);
      reject(new Error(`WebSocket 连接失败。Relay Server 可能未启动或 token 已过期。`));
    };

    socket.onclose = () => {
      ws = null;
      sessionId = null;
      for (const [id, pending] of pendingRequests) {
        clearTimeout(pending.timeout);
        pending.reject(new Error("Connection closed"));
      }
      pendingRequests.clear();
    };
  });
}

function handleWsMessage(msg) {
  if (msg.id !== undefined && pendingRequests.has(msg.id)) {
    const pending = pendingRequests.get(msg.id);
    clearTimeout(pending.timeout);
    pendingRequests.delete(msg.id);
    pending.resolve(msg);
    return;
  }

  if (msg.method) {
    if (msg.method === "Target.attachedToTarget") {
      const params = msg.params || {};
      if (params.sessionId) sessionId = params.sessionId;
      if (params.targetInfo?.targetId) targetId = params.targetInfo;
    }
  }
}

async function sendCDPCommand(method, params = {}, options = {}) {
  await ensureConnection();
  const id = msgId++;
  const msg = { id, method, params };

  if (options.sessionId || sessionId) {
    msg.sessionId = options.sessionId || sessionId;
  }

  return new Promise((resolve, reject) => {
    const timeoutMs = options.timeout || 30000;
    const timeout = setTimeout(() => {
      pendingRequests.delete(id);
      reject(new Error(`CDP command timeout: ${method} (${timeoutMs}ms)`));
    }, timeoutMs);

    pendingRequests.set(id, { resolve, reject, timeout });

    try {
      ws.send(JSON.stringify(msg));
    } catch (err) {
      clearTimeout(timeout);
      pendingRequests.delete(id);
      reject(err);
    }
  });
}

// ============================================================
// HTTP API 辅助
// ============================================================
async function httpGet(path) {
  const resp = await fetch(`${RELAY_URL}${path}`, { signal: AbortSignal.timeout(5000) });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${path}`);
  return resp.json();
}

// ============================================================
// 高级浏览器操作
// ============================================================

async function listAndAttach() {
  const targetsResp = await sendCDPCommand("Target.getTargets");
  const targets = targetsResp?.result?.targetInfos || [];

  if (targets.length === 0) {
    throw new Error(
      "没有发现任何浏览器标签页。请确保：\n" +
      "1. Chrome 浏览器已打开\n" +
      "2. LaoLiu Browser Relay Extension 已安装并显示绿色 Connected 状态\n" +
      `3. Extension 目录: ${EXTENSION_DIR}`
    );
  }

  let target = targets.find(t => t.type === "page" && !t.attached) ||
               targets.find(t => t.type === "page") ||
               targets[0];

  // 不再缓存 sessionId，每次都重新 attach（Extension 已处理重复 attach 的情况）
  const attachResp = await sendCDPCommand("Target.attachToTarget", {
    targetId: target.targetId,
    flatten: true,
  }, { sessionId: undefined });

  const newSessionId = attachResp?.result?.sessionId;
  if (newSessionId) {
    sessionId = newSessionId;
    targetId = target.targetId;
  }

  return { sessionId, targetId: target.targetId };
}

// ============================================================
// MCP 工具定义
// ============================================================
const TOOLS = [
  {
    name: "browser_status",
    description: "检查 老六浏览器 连接状态：Extension 是否已连接、加密是否激活、有哪些标签页。首次调用会自动启动 Relay Server。",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_navigate",
    description: "导航浏览器到指定 URL。会自动 attach 到第一个可用的标签页。",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string", description: "目标 URL" } },
      required: ["url"],
    },
  },
  {
    name: "browser_evaluate",
    description: "在浏览器中执行 JavaScript 表达式并返回结果。可读取 DOM、获取数据等。",
    inputSchema: {
      type: "object",
      properties: {
        expression: { type: "string", description: "JavaScript 表达式" },
        awaitPromise: { type: "boolean", description: "等待 Promise（默认 false）", default: false },
      },
      required: ["expression"],
    },
  },
  {
    name: "browser_screenshot",
    description: "对当前浏览器页面截图，返回 base64 PNG 图片。",
    inputSchema: {
      type: "object",
      properties: {
        quality: { type: "integer", description: "JPEG 质量 0-100", default: 80 },
        format: { type: "string", enum: ["png", "jpeg"], description: "图片格式", default: "png" },
      },
    },
  },
  {
    name: "browser_click",
    description: "点击页面中指定 CSS 选择器的元素。",
    inputSchema: {
      type: "object",
      properties: { selector: { type: "string", description: "CSS 选择器" } },
      required: ["selector"],
    },
  },
  {
    name: "browser_type",
    description: "在指定 CSS 选择器的输入框中输入文本。",
    inputSchema: {
      type: "object",
      properties: {
        selector: { type: "string", description: "CSS 选择器" },
        text: { type: "string", description: "要输入的文本" },
        clear: { type: "boolean", description: "先清空输入框（默认 true）", default: true },
      },
      required: ["selector", "text"],
    },
  },
  {
    name: "browser_list_tabs",
    description: "列出浏览器中所有打开的标签页。",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_cdp",
    description: "发送原始 CDP 命令（高级）。参考 Chrome DevTools Protocol。",
    inputSchema: {
      type: "object",
      properties: {
        method: { type: "string", description: "CDP 方法名" },
        params: { type: "object", description: "CDP 参数" },
      },
      required: ["method"],
    },
  },
  // ── Extension.* 高级工具 ──
  {
    name: "browser_press_key",
    description: "模拟键盘按键，支持组合键如 Ctrl+A、Shift+Enter、F1-F12 等。可向当前焦点元素发送按键事件。",
    inputSchema: {
      type: "object",
      properties: {
        key: { type: "string", description: "按键或组合键，例如 Enter、Tab、Escape、Ctrl+A、Shift+Enter、F5" },
      },
      required: ["key"],
    },
  },
  {
    name: "browser_scroll",
    description: "滚动页面或容器。支持方向滚动、滚到底部、指定滚动量。",
    inputSchema: {
      type: "object",
      properties: {
        direction: { type: "string", enum: ["up", "down", "left", "right"], description: "滚动方向（默认 down）", default: "down" },
        amount: { type: "integer", description: "滚动像素量（默认视口高度 60%）" },
        toEnd: { type: "boolean", description: "滚动到边界（底部/顶部）", default: false },
      },
    },
  },
  {
    name: "browser_find_keyword",
    description: "在页面内搜索关键词，返回匹配结果及上下文。支持中英文，使用句子分割提供精准上下文。",
    inputSchema: {
      type: "object",
      properties: {
        keyword: { type: "string", description: "要搜索的关键词" },
      },
      required: ["keyword"],
    },
  },
  {
    name: "browser_move_mouse",
    description: "将鼠标移动到指定元素或坐标位置，触发 hover 状态（如显示下拉菜单、工具提示等）。",
    inputSchema: {
      type: "object",
      properties: {
        selector: { type: "string", description: "CSS 选择器（与 index 二选一）" },
        index: { type: "integer", description: "元素索引编号（需先 markElements）" },
        x: { type: "number", description: "X 坐标" },
        y: { type: "number", description: "Y 坐标" },
      },
    },
  },
  {
    name: "browser_screenshot_annotated",
    description: "截取页面并自动标注所有可交互元素（按钮、输入框、链接等），每个元素带编号标签。返回带标注的截图和元素列表。",
    inputSchema: {
      type: "object",
      properties: {
        maxElements: { type: "integer", description: "最大标注元素数（默认 200）", default: 200 },
        format: { type: "string", enum: ["png", "jpeg"], description: "图片格式", default: "png" },
      },
    },
  },
  {
    name: "browser_extract_content",
    description: "提取页面正文内容，返回 Markdown 格式文本。双路径提取：DOM walker + Readability 评分，自动选择最优结果。",
    inputSchema: {
      type: "object",
      properties: {
        enhanced: { type: "boolean", description: "使用增强提取（Readability 评分），默认 false", default: false },
      },
    },
  },
  {
    name: "browser_input_rich",
    description: "向富文本编辑器输入内容。自动检测并处理 DraftEditor、Slate、ProseMirror、contenteditable 等编辑器类型。",
    inputSchema: {
      type: "object",
      properties: {
        selector: { type: "string", description: "CSS 选择器（与 index 二选一）" },
        index: { type: "integer", description: "元素索引编号（需先 markElements）" },
        text: { type: "string", description: "要输入的文本" },
      },
      required: ["text"],
    },
  },
  {
    name: "browser_action_mask",
    description: "控制页面操作遮罩。ongoing=阻止用户操作+显示\"老六正在操作\"，idle=移除遮罩，takeover=透明遮罩允许用户操作。",
    inputSchema: {
      type: "object",
      properties: {
        state: { type: "string", enum: ["ongoing", "idle", "takeover"], description: "遮罩状态", default: "ongoing" },
      },
    },
  },
];

// ============================================================
// MCP 工具处理
// ============================================================
async function handleToolCall(name, args) {
  try {
    switch (name) {
      case "browser_status": {
        // 确保 Relay 可用
        await ensureRelay();
        const status = await httpGet("/status");
        const targets = await httpGet("/json/list");
        return {
          content: [{
            type: "text",
            text: `老六浏览器连接状态:\n` +
                  `- Extension 已连接: ${status.extension_connected ? "是" : "否"}\n` +
                  `- 加密通道: ${status.encryption_active ? "已激活" : "未激活"}\n` +
                  `- 标签页数量: ${targets.length}\n` +
                  (targets.length > 0
                    ? targets.map((t, i) => `  [${i+1}] ${t.title || "无标题"} - ${t.url || "about:blank"}`).join("\n")
                    : "  (无标签页。请在 Chrome 中打开页面并确保 Extension 已连接)") +
                  `\n\n项目目录: ${PROJECT_DIR}\nRelay Server: ${RELAY_URL}`,
          }],
        };
      }

      case "browser_navigate": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        await sendCDPCommand("Page.enable", {}, { sessionId: sid });
        await sendCDPCommand("Page.navigate", { url: args.url }, { sessionId: sid, timeout: 15000 });
        await new Promise(r => setTimeout(r, 1000));
        const titleResp = await sendCDPCommand("Runtime.evaluate", { expression: "document.title" }, { sessionId: sid });
        const title = titleResp?.result?.result?.value || "未知";
        return { content: [{ type: "text", text: `已导航到: ${args.url}\n页面标题: ${title}` }] };
      }

      case "browser_evaluate": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const resp = await sendCDPCommand("Runtime.evaluate", {
          expression: args.expression, awaitPromise: args.awaitPromise || false, returnByValue: true,
        }, { sessionId: sid });
        const result = resp?.result;
        if (result?.exceptionDetails) {
          return { content: [{ type: "text", text: `JavaScript 执行错误: ${result.exceptionDetails.text}\n${result.exceptionDetails.exception?.description || ""}` }], isError: true };
        }
        const value = result?.result?.value;
        const text = value !== undefined ? (typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)) : `(${result?.result?.type || "undefined"})`;
        return { content: [{ type: "text", text }] };
      }

      case "browser_screenshot": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const format = args.format || "png";
        const resp = await sendCDPCommand("Page.captureScreenshot", {
          format, quality: format === "jpeg" ? (args.quality || 80) : undefined,
        }, { sessionId: sid });
        const data = resp?.result?.data;
        if (!data) return { content: [{ type: "text", text: "截图失败" }], isError: true };
        return { content: [{ type: "image", data, mimeType: format === "jpeg" ? "image/jpeg" : "image/png" }] };
      }

      case "browser_click": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const locResp = await sendCDPCommand("Runtime.evaluate", {
          expression: `(() => { const el = document.querySelector(${JSON.stringify(args.selector)}); if (!el) return { error: "Element not found" }; el.scrollIntoView({ behavior: "instant", block: "center" }); const r = el.getBoundingClientRect(); return { x: r.x + r.width/2, y: r.y + r.height/2 }; })()`,
          returnByValue: true,
        }, { sessionId: sid });
        const loc = locResp?.result?.result?.value;
        if (!loc || loc.error) return { content: [{ type: "text", text: `未找到元素: ${args.selector}` }], isError: true };
        await new Promise(r => setTimeout(r, 300));
        await sendCDPCommand("Input.dispatchMouseEvent", { type: "mousePressed", x: loc.x, y: loc.y, button: "left", clickCount: 1 }, { sessionId: sid });
        await sendCDPCommand("Input.dispatchMouseEvent", { type: "mouseReleased", x: loc.x, y: loc.y, button: "left", clickCount: 1 }, { sessionId: sid });
        return { content: [{ type: "text", text: `已点击: ${args.selector} (${Math.round(loc.x)}, ${Math.round(loc.y)})` }] };
      }

      case "browser_type": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const focusResp = await sendCDPCommand("Runtime.evaluate", {
          expression: `(() => { const el = document.querySelector(${JSON.stringify(args.selector)}); if (!el) return { error: "Element not found" }; el.scrollIntoView({ behavior: "instant", block: "center" }); el.focus(); ${args.clear !== false ? "el.value = '';" : ""} el.dispatchEvent(new Event('input', { bubbles: true })); return { ok: true }; })()`,
          returnByValue: true,
        }, { sessionId: sid });
        if (!focusResp?.result?.result?.value?.ok) return { content: [{ type: "text", text: `未找到输入元素: ${args.selector}` }], isError: true };
        await new Promise(r => setTimeout(r, 200));
        for (const char of args.text) {
          await sendCDPCommand("Input.dispatchKeyEvent", { type: "keyDown", text: char, key: char }, { sessionId: sid });
          await sendCDPCommand("Input.dispatchKeyEvent", { type: "keyUp", key: char }, { sessionId: sid });
        }
        return { content: [{ type: "text", text: `已输入: "${args.text}" → ${args.selector}` }] };
      }

      case "browser_list_tabs": {
        await ensureRelay();
        const targets = await httpGet("/json/list");
        if (targets.length === 0) return { content: [{ type: "text", text: "没有标签页。请打开 Chrome 并确保 Extension 已连接。" }] };
        const lines = targets.map((t, i) => `[${i+1}] ${t.title || "无标题"} - ${t.url || "about:blank"} (${t.attached ? "已附加" : "未附加"})`);
        return { content: [{ type: "text", text: `标签页 (${targets.length}):\n${lines.join("\n")}` }] };
      }

      case "browser_cdp": {
        await ensureConnection();
        const resp = await sendCDPCommand(args.method, args.params || {}, { timeout: 30000 });
        return { content: [{ type: "text", text: JSON.stringify(resp?.result || resp?.error || resp, null, 2) }] };
      }

      case "browser_press_key": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const resp = await sendCDPCommand("Extension.pressKey", { key: args.key }, { sessionId: sid });
        const result = resp?.result;
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
      }

      case "browser_scroll": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const params = { direction: args.direction || "down" };
        if (args.amount != null) params.amount = args.amount;
        if (args.toEnd) params.toEnd = true;
        const resp = await sendCDPCommand("Extension.scroll", params, { sessionId: sid });
        const result = resp?.result;
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
      }

      case "browser_find_keyword": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const resp = await sendCDPCommand("Extension.findKeyword", { keyword: args.keyword }, { sessionId: sid });
        const result = resp?.result;
        if (!result?.success) return { content: [{ type: "text", text: `搜索失败: ${result?.error || "未知错误"}` }], isError: true };
        const lines = result.matches.map((m, i) => `[${i + 1}] ...${m.context}...`);
        const text = `找到 ${result.count} 处匹配 "${result.keyword}":\n${lines.join("\n")}`;
        return { content: [{ type: "text", text }] };
      }

      case "browser_move_mouse": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const params = {};
        if (args.selector) params.selector = args.selector;
        if (args.index != null) params.index = args.index;
        if (args.x != null) params.x = args.x;
        if (args.y != null) params.y = args.y;
        const resp = await sendCDPCommand("Extension.moveMouse", params, { sessionId: sid });
        const result = resp?.result;
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
      }

      case "browser_screenshot_annotated": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const params = {};
        if (args.maxElements) params.maxElements = args.maxElements;
        if (args.format) params.format = args.format;
        const resp = await sendCDPCommand("Extension.captureHighlightedViewport", params, { sessionId: sid, timeout: 30000 });
        const result = resp?.result;
        if (!result?.data) return { content: [{ type: "text", text: "截图失败" }], isError: true };
        const elements = (result.elements || []).map(e => `[${e.idx}] <${e.tag}> ${e.text || "(无文本)"}`).join("\n");
        return {
          content: [
            { type: "image", data: result.data, mimeType: "image/png" },
            { type: "text", text: `标注了 ${result.elements?.length || 0} 个可交互元素:\n${elements}` },
          ],
        };
      }

      case "browser_extract_content": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const method = args.enhanced ? "Extension.extractContentEnhanced" : "Extension.extractContent";
        const resp = await sendCDPCommand(method, {}, { sessionId: sid, timeout: 15000 });
        const result = resp?.result;
        if (!result) return { content: [{ type: "text", text: "提取失败" }], isError: true };
        const methodLabel = result.method ? ` (${result.method})` : "";
        return { content: [{ type: "text", text: `标题: ${result.title}\nURL: ${result.url}\n\n${result.content}${methodLabel}` }] };
      }

      case "browser_input_rich": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const params = { text: args.text };
        if (args.selector) params.selector = args.selector;
        if (args.index != null) params.index = args.index;
        const resp = await sendCDPCommand("Extension.inputEnhanced", params, { sessionId: sid });
        const result = resp?.result;
        if (!result?.success) return { content: [{ type: "text", text: `输入失败: ${result?.error || "未知错误"}` }], isError: true };
        return { content: [{ type: "text", text: `已输入（${result.method}）: "${args.text}"` }] };
      }

      case "browser_action_mask": {
        await ensureConnection();
        const { sessionId: sid } = await listAndAttach();
        const state = args.state || "ongoing";
        const resp = await sendCDPCommand("Extension.actionMask", { state }, { sessionId: sid });
        const result = resp?.result;
        const stateText = { ongoing: "已开启操作遮罩 🔒", idle: "已移除操作遮罩 ✅", takeover: "已切换为接管模式" };
        return { content: [{ type: "text", text: stateText[state] || `遮罩状态: ${state}` }] };
      }

      default:
        return { content: [{ type: "text", text: `未知工具: ${name}` }], isError: true };
    }
  } catch (err) {
    return { content: [{ type: "text", text: `错误: ${err.message}` }], isError: true };
  }
}

// ============================================================
// MCP Server 启动
// ============================================================
const server = new Server(
  { name: "laoliu-browser-relay", version: "2.3.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  return await handleToolCall(request.params.name, request.params.arguments || {});
});

async function main() {
  // 启动时自检
  const deps = checkDependencies();
  if (!deps.ok) {
    log("依赖检查发现问题:");
    for (const issue of deps.issues) {
      log(`  - ${issue}`);
    }
    log("MCP Server 将继续启动，但部分功能可能不可用。");
  } else {
    log(`依赖检查通过 ✅ (python=${deps.python})`);
    log(`项目目录: ${PROJECT_DIR}`);
    log(`Relay Server 目录: ${RELAY_SERVER_DIR}`);
    log(`Extension 目录: ${EXTENSION_DIR}`);
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
  log("MCP Server 已就绪 ✅");
}

main().catch((err) => {
  process.stderr.write(`LaoLiu MCP Server 启动失败: ${err.message}\n`);
  process.exit(1);
});
