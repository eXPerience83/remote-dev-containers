import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { createServer } from "node:http";

// Runtime CI fixture only: MCP functionality, not the production sandbox boundary.
const server = createServer((req, res) => {
  if (req.url !== "/") { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end('<title>remote-dev-mcp-smoke</title><main id="marker">LOCAL-MCP-PASS</main>');
});
// An upgraded WebSocket is not covered by server.closeAllConnections().
const upgradedSockets = new Set();
server.on("upgrade", (req, socket) => {
  upgradedSockets.add(socket);
  socket.once("close", () => upgradedSockets.delete(socket));
  if (req.url !== "/ws" || !req.headers["sec-websocket-key"]) { socket.destroy(); return; }
  const key = createHash("sha1")
    .update(req.headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
    .digest("base64");
  socket.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + key + "\r\n\r\n");
  socket.write(Buffer.concat([Buffer.from([0x81, 0x04]), Buffer.from("pong")]), () => socket.end());
});

let child, pending = new Map(), buffer = "", nextId = 0, stderrTail = "";
const watchdog = setTimeout(() => {
  console.error("Playwright MCP smoke exceeded 60 seconds");
  child?.kill("SIGKILL");
  process.exit(1);
}, 60000);
function rejectPending(error) {
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
}
function request(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(method + " timed out"));
    }, 30000);
    pending.set(id, { resolve, reject, timer });
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  });
}
function resultText(result, name) {
  if (result?.isError) throw new Error(name + " failed: " + JSON.stringify(result.content).slice(0, 700));
  return JSON.stringify(result?.content ?? []);
}

// The fixture must inspect the *real* sandboxed MCP Node process, not the
// root supervisor. Linux /proc/<pid>/status is readable without ptrace rights.
function assertSandboxedNode() {
  const match = "/opt/remote-dev/playwright/node_modules/@playwright/mcp/cli.js";
  const candidates = [];
  for (const name of readdirSync("/proc")) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const cmdline = readFileSync("/proc/" + name + "/cmdline", "utf8");
      if (!cmdline.includes(match)) continue;
      const status = readFileSync("/proc/" + name + "/status", "utf8");
      candidates.push(status);
    } catch { /* Process exited between listing and inspection. */ }
  }
  if (candidates.length !== 1) {
    throw new Error("Expected one sandboxed MCP Node process, got " + candidates.length);
  }
  const status = candidates[0];
  const get = key => status.match(new RegExp("^" + key + ":\\s*([^\\n]+)", "m"))?.[1];
  const uid = get("Uid")?.split(/\s+/)[0];
  const gid = get("Gid")?.split(/\s+/)[0];
  if (uid !== "61123" || gid !== "61123")
    throw new Error("MCP Node process UID/GID was not dropped");
  if (get("CapEff")?.trim() !== "0000000000000000" ||
      get("CapPrm")?.trim() !== "0000000000000000")
    throw new Error("MCP Node process still has Linux capabilities");
  if (get("NoNewPrivs")?.trim() !== "1")
    throw new Error("MCP Node process lost NoNewPrivs");
}

try {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  child = spawn("/usr/local/bin/remote-dev-playwright-mcp", [], {
    stdio: ["pipe", "pipe", "pipe"], env: { ...process.env },
  });
  child.stderr.on("data", chunk => { stderrTail = (stderrTail + chunk.toString()).slice(-2000); });
  child.stdout.on("data", chunk => {
    buffer += chunk.toString();
    for (let end = buffer.indexOf("\n"); end >= 0; end = buffer.indexOf("\n")) {
      const line = buffer.slice(0, end).trim();
      buffer = buffer.slice(end + 1);
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); }
      catch { rejectPending(new Error("Invalid MCP JSON-RPC response")); continue; }
      const item = pending.get(message.id);
      if (!item) continue;
      pending.delete(message.id);
      clearTimeout(item.timer);
      if (message.error) item.reject(new Error(JSON.stringify(message.error)));
      else item.resolve(message.result);
    }
  });
  child.on("error", rejectPending);
  child.on("exit", (code, signal) => rejectPending(new Error("MCP exited: " + (code ?? signal))));
  await request("initialize", {
    protocolVersion: "2025-03-26", capabilities: {},
    clientInfo: { name: "remote-dev-browser-smoke", version: "1.0.0" },
  });
  child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
  const tools = new Set((await request("tools/list")).tools?.map(tool => tool.name));
  for (const tool of ["browser_navigate", "browser_evaluate", "browser_take_screenshot", "browser_close"]) {
    if (!tools.has(tool)) throw new Error("MCP tool missing: " + tool);
  }
  resultText(await request("tools/call", {
    name: "browser_navigate", arguments: { url: "http://127.0.0.1:" + port + "/" },
  }), "browser_navigate");
  const dom = resultText(await request("tools/call", {
    name: "browser_evaluate",
    arguments: { function: "() => document.title + ':' + document.querySelector('#marker').textContent" },
  }), "DOM/JavaScript");
  if (!dom.includes("remote-dev-mcp-smoke:LOCAL-MCP-PASS")) throw new Error("DOM/JavaScript mismatch");
  const websocket = resultText(await request("tools/call", {
    name: "browser_evaluate",
    arguments: { function: "async () => await new Promise((resolve, reject) => { const ws = new WebSocket('ws://' + location.host + '/ws'); ws.onmessage = event => { resolve(event.data); ws.close(); }; ws.onerror = () => reject(new Error('WebSocket failed')); setTimeout(() => reject(new Error('WebSocket timed out')), 4000); })" },
  }), "WebSocket");
  if (!websocket.includes("pong")) throw new Error("WebSocket mismatch");
  assertSandboxedNode();
  const screenshot = await request("tools/call", {
    name: "browser_take_screenshot", arguments: { type: "png" },
  });
  if (screenshot?.isError || !screenshot?.content?.some(item => item.type === "image")) {
    throw new Error("MCP screenshot did not return an image");
  }
  resultText(await request("tools/call", { name: "browser_close", arguments: {} }), "browser_close");
  console.log("Playwright MCP stdio, tools, local HTTP, JavaScript and WebSocket: OK");
} catch (error) {
  console.error("Playwright MCP smoke: " + error.message);
  if (stderrTail) console.error("MCP stderr tail: " + stderrTail);
  process.exitCode = 1;
} finally {
  clearTimeout(watchdog);
  if (child && child.exitCode === null) {
    child.stdin.end();
    const exited = new Promise(resolve => child.once("exit", resolve));
    await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 1500))]);
    if (child.exitCode === null) child.kill("SIGTERM");
  }
  rejectPending(new Error("Smoke test finished"));
  for (const socket of upgradedSockets) socket.destroy();
  server.closeAllConnections();
  await new Promise((resolve, reject) => {
    const deadline = setTimeout(
      () => reject(new Error("MCP fixture server teardown timed out")), 5000);
    server.close(error => {
      clearTimeout(deadline);
      if (error) reject(error);
      else resolve();
    });
  });
}
