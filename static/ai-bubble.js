// AI Nurse chat bubble. Add to any page with one script tag.
(function () {
  const css = `
    #ain-btn { position: fixed; right: 20px; bottom: 20px; z-index: 9999; background: #1f5f8b; color: #fff;
      border: 0; border-radius: 24px; padding: 12px 20px; font: 600 14px system-ui, "Segoe UI", sans-serif;
      box-shadow: 0 4px 14px rgba(0,0,0,.18); cursor: pointer; }
    #ain-panel { position: fixed; right: 20px; bottom: 76px; z-index: 9999; width: 360px; max-width: calc(100vw - 32px);
      height: 500px; max-height: calc(100vh - 110px); background: #fff; color: #1f2933; border: 1px solid #d9dee4;
      border-radius: 10px; box-shadow: 0 8px 28px rgba(0,0,0,.18); display: none; flex-direction: column;
      font: 14px/1.45 system-ui, "Segoe UI", sans-serif; overflow: hidden; }
    #ain-panel.open { display: flex; }
    #ain-head { padding: 10px 12px; border-bottom: 1px solid #d9dee4; background: #f5f6f8; }
    #ain-head .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    #ain-head b { font-size: 15px; }
    #ain-close { background: none; border: 0; font-size: 13px; color: #616e7c; cursor: pointer; }
    #ain-model { width: 100%; padding: 6px; border: 1px solid #d9dee4; border-radius: 6px; font: inherit; background: #fff; }
    #ain-msgs { flex: 1; overflow-y: auto; padding: 12px; background: #fff; }
    .ain-msg { margin-bottom: 10px; padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; max-width: 88%; }
    .ain-user { background: #1f5f8b; color: #fff; margin-left: auto; }
    .ain-bot { background: #f0f2f5; }
    .ain-err { background: #fdecea; color: #b42318; }
    .ain-tag { display: block; font-size: 11px; font-weight: 600; margin-bottom: 4px; }
    .ain-tag.ok { color: #1e7a4c; } .ain-tag.gen { color: #9a6700; }
    .ain-meta { display: block; font-size: 11px; color: #616e7c; margin-top: 4px; }
    #ain-form { display: flex; gap: 6px; padding: 10px; border-top: 1px solid #d9dee4; }
    #ain-input { flex: 1; padding: 8px; border: 1px solid #d9dee4; border-radius: 6px; font: inherit; resize: none; height: 40px; }
    #ain-send { background: #1f5f8b; color: #fff; border: 0; border-radius: 6px; padding: 0 14px; font-weight: 600; cursor: pointer; }
    #ain-send:disabled { opacity: .55; cursor: wait; }
  `;

  function el(tag, attrs, text) {
    const e = document.createElement(tag);
    Object.assign(e, attrs || {});
    if (text) e.textContent = text;
    return e;
  }

  document.head.appendChild(el("style", {}, css));

  const btn = el("button", { id: "ain-btn", type: "button" }, "AI Nurse");
  const panel = el("div", { id: "ain-panel" });
  const head = el("div", { id: "ain-head" });
  const top = el("div", { className: "top" });
  top.append(el("b", {}, "AI Nurse"), el("button", { id: "ain-close", type: "button" }, "Close"));
  const model = el("select", { id: "ain-model", title: "AI model" });
  head.append(top, model);
  const msgs = el("div", { id: "ain-msgs" });
  const form = el("form", { id: "ain-form" });
  const input = el("textarea", { id: "ain-input", placeholder: "Ask a care question..." });
  const send = el("button", { id: "ain-send", type: "submit" }, "Send");
  form.append(input, send);
  panel.append(head, msgs, form);
  document.body.append(panel, btn);

  function addMsg(kind, text) {
    const m = el("div", { className: "ain-msg ain-" + kind }, text);
    msgs.appendChild(m);
    msgs.scrollTop = msgs.scrollHeight;
    return m;
  }

  let loaded = false;
  async function loadModels() {
    loaded = true;
    model.replaceChildren(new Option("Loading models...", ""));
    try {
      const data = await (await fetch("/api/ask/models")).json();
      model.replaceChildren();
      if (!data.ollama_running) {
        model.add(new Option("No models found", ""));
        addMsg("err", "Ollama is not running. Start it with: ollama serve");
        loaded = false;
        return;
      }
      for (const name of data.models) {
        const label = name === data.default ? name + " (recommended)" : name;
        model.add(new Option(label, name, false, name === data.default));
      }
    } catch (e) {
      model.replaceChildren(new Option("Server not reachable", ""));
      loaded = false;
    }
  }

  btn.addEventListener("click", () => {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) {
      if (!loaded) loadModels();
      if (!msgs.children.length) addMsg("bot", "Hi, ask me a care question. This uses fake data only, so always check with the RN in charge.");
      input.focus();
    }
  });
  document.getElementById("ain-close").addEventListener("click", () => panel.classList.remove("open"));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (question.length === 0) return;
    addMsg("user", question);
    input.value = "";
    send.disabled = true;
    const wait = addMsg("bot", "Thinking... on CPU this can take a little while.");
    const started = Date.now();
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, model: model.value || null }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please ask a longer question");
      wait.replaceChildren(
        el("span", { className: "ain-tag " + (data.grounded ? "ok" : "gen") },
          data.grounded ? "From approved guidance" : "General answer, not from approved guidance"),
        document.createTextNode(data.answer)
      );
      let meta = data.model + " · " + ((Date.now() - started) / 1000).toFixed(1) + "s";
      if (data.sources.length) meta += " · " + data.sources.join(", ");
      wait.appendChild(el("span", { className: "ain-meta" }, meta));
    } catch (err) {
      wait.className = "ain-msg ain-err";
      wait.textContent = err.message || "Something went wrong";
    } finally {
      send.disabled = false;
      msgs.scrollTop = msgs.scrollHeight;
    }
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
})();