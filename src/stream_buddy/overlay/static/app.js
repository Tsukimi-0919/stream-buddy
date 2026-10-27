// stream-buddy のページ。サーバーから受け取ったメッセージどおりに表示する。
// 仕様は docs/ws-protocol.md。文字の表示は textContent だけを使う (SR-04)。
// トークンや URL はどこにも出力しない。
"use strict";

(() => {
  const PROTOCOL_VERSION = 0;
  const PAGE_VERSION = "0.1.0";
  const SAY_DURATION_MS = 5000;
  const RETRY_MIN_MS = 1000;
  const RETRY_MAX_MS = 10000;

  const body = document.body;
  const buddy = document.getElementById("buddy");
  const bubble = document.getElementById("bubble");
  const bubbleText = document.getElementById("bubble-text");
  const debugTension = document.getElementById("debug-tension");

  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") || "";
  // 確認用: debug=1 のときだけ、受け取ったテンションの名前を隅に出す
  const debug = params.get("debug") === "1";
  const socketUrl =
    "ws://127.0.0.1:" + window.location.port + "/ws?token=" + encodeURIComponent(token);

  // 表示

  let sayTimer = null;

  function setTension(level) {
    buddy.dataset.tension = level;
    if (debug) {
      debugTension.textContent = level;
      debugTension.hidden = false;
    }
  }

  function setSpeaking(speaking) {
    buddy.classList.toggle("is-speaking", speaking);
  }

  function showSay(text) {
    bubbleText.textContent = text;
    bubble.hidden = false;
    clearTimeout(sayTimer);
    sayTimer = setTimeout(hideSay, SAY_DURATION_MS);
  }

  function hideSay() {
    bubble.hidden = true;
    bubbleText.textContent = "";
    sayTimer = null;
  }

  // 受信メッセージの検証

  function isPlainObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function hasExactKeys(obj, keys) {
    const actual = Object.keys(obj);
    return actual.length === keys.length && keys.every((key) => Object.hasOwn(obj, key));
  }

  function isStringOfLength(value, min, max) {
    if (typeof value !== "string") {
      return false;
    }
    // サーバー側 (Python) と同じく、コードポイントの数で数える
    const length = Array.from(value).length;
    return length >= min && length <= max;
  }

  const handlers = new Map([
    [
      "speech",
      {
        keys: ["speaking"],
        valid: (p) => typeof p.speaking === "boolean",
        apply: (p) => setSpeaking(p.speaking),
      },
    ],
    [
      "tension",
      {
        keys: ["level"],
        valid: (p) => ["calm", "normal", "high"].includes(p.level),
        apply: (p) => setTension(p.level),
      },
    ],
    [
      "say",
      {
        keys: ["line_id", "text"],
        valid: (p) => isStringOfLength(p.line_id, 1, 64) && isStringOfLength(p.text, 1, 80),
        apply: (p) => showSay(p.text),
      },
    ],
    [
      "effect",
      {
        keys: ["kind"],
        valid: (p) => ["death", "clear"].includes(p.kind),
        // 演出は Phase 3 で作る
        apply: () => {},
      },
    ],
    [
      "display",
      {
        keys: ["background"],
        valid: (p) => ["transparent", "chroma"].includes(p.background),
        apply: (p) => {
          body.dataset.background = p.background;
        },
      },
    ],
  ]);

  function handleMessage(data) {
    if (typeof data !== "string") {
      return;
    }
    let message;
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    if (!isPlainObject(message) || !hasExactKeys(message, ["v", "type", "payload"])) {
      return;
    }
    if (message.v !== PROTOCOL_VERSION) {
      return;
    }
    const handler = handlers.get(message.type);
    const payload = message.payload;
    if (!handler || !isPlainObject(payload) || !hasExactKeys(payload, handler.keys)) {
      return;
    }
    if (!handler.valid(payload)) {
      return;
    }
    handler.apply(payload);
  }

  // 接続と再接続

  let retryMs = RETRY_MIN_MS;

  function scheduleReconnect() {
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, RETRY_MAX_MS);
  }

  function connect() {
    let socket;
    try {
      socket = new WebSocket(socketUrl);
    } catch {
      scheduleReconnect();
      return;
    }
    socket.addEventListener("open", () => {
      retryMs = RETRY_MIN_MS;
      const hello = { v: PROTOCOL_VERSION, type: "hello", payload: { page_version: PAGE_VERSION } };
      socket.send(JSON.stringify(hello));
    });
    socket.addEventListener("message", (event) => handleMessage(event.data));
    // error のあとには必ず close が来るので、再接続は close だけで行う
    socket.addEventListener("close", () => {
      setSpeaking(false);
      scheduleReconnect();
    });
  }

  connect();
})();
