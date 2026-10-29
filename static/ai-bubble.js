// AI Nurse chat bubble. Add to any page with one script tag.
// On the dashboard it reads the selected resident and role, so answers use that resident's approved guidance.
(function () {
  const css = `
    #ain-btn, #ain-panel {
      --a: var(--accent, #0F5F5A);
      --s: var(--card, #FFFFFF);
      --i: var(--ink, #1C1F1E);
      --i2: var(--ink-secondary, #4A5553);
      --l: var(--line, #E3E1DC);
      --b: var(--bg, #F6F5F2);
      font-family: var(--font-sans, "Source Sans 3", -apple-system, sans-serif);
    }
    #ain-btn {
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: 9999;
      background: var(--a);
      color: #FFFFFF;
      border: 1px solid rgba(0, 0, 0, 0.1);
      border-radius: var(--radius-pill, 999px);
      padding: 10px 18px 10px 14px;
      font-size: 14px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      transition: background-color 120ms ease;
    }
    #ain-btn:hover {
      background: var(--accent-hover, #0A4541);
    }
    #ain-btn .pulse {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #48A856;
    }
    #ain-btn.off .pulse {
      background: #E0584E;
    }
    #ain-panel {
      position: fixed;
      right: 20px;
      bottom: 74px;
      z-index: 9999;
      width: 380px;
      max-width: calc(100vw - 32px);
      height: 520px;
      max-height: calc(100vh - 100px);
      background: var(--s);
      color: var(--i);
      border: 1px solid var(--l);
      border-radius: var(--radius-card, 6px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
      display: none;
      flex-direction: column;
      font-size: 14px;
      line-height: 1.45;
      overflow: hidden;
    }
    #ain-panel.open {
      display: flex;
    }
    #ain-head {
      padding: 12px 14px;
      background: var(--a);
      color: #FFFFFF;
    }
    #ain-head .top {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #ain-head b {
      font-size: 15px;
      font-weight: 600;
    }
    #ain-about {
      font-size: 12px;
      color: rgba(255, 255, 255, 0.85);
      margin: 2px 0 8px;
    }
    #ain-close {
      background: rgba(255, 255, 255, 0.15);
      border: 0;
      color: #FFFFFF;
      font-size: 12px;
      border-radius: var(--radius-input, 4px);
      padding: 4px 8px;
      cursor: pointer;
    }
    #ain-close:hover {
      background: rgba(255, 255, 255, 0.25);
    }
    #ain-model {
      width: 100%;
      padding: 6px 8px;
      border: 1px solid rgba(255, 255, 255, 0.3);
      border-radius: var(--radius-input, 4px);
      font: inherit;
      font-size: 12.5px;
      background: rgba(255, 255, 255, 0.15);
      color: #FFFFFF;
    }
    #ain-model option {
      color: #1C1F1E;
      background: #FFFFFF;
    }
    #ain-msgs {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      background: var(--b);
    }
    .ain-msg {
      margin-bottom: 8px;
      padding: 8px 10px;
      border-radius: var(--radius-card, 6px);
      white-space: pre-line;
      max-width: 90%;
      background: var(--s);
      border: 1px solid var(--l);
      font-size: 13.5px;
    }
    .ain-user {
      background: var(--accent-soft, #E6F0EF);
      border-color: var(--accent-border, #BCD9D6);
      color: var(--accent, #0F5F5A);
      margin-left: auto;
    }
    .ain-bot {
      margin-right: auto;
    }
    .ain-err {
      background: var(--red-soft, #FDF0EF);
      color: var(--red, #A1281F);
      border-color: var(--red-border, #F5C7C3);
    }
    .ain-tag {
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      border-radius: var(--radius-pill, 999px);
      padding: 1px 6px;
      margin-bottom: 4px;
    }
    .ain-tag.ok {
      background: var(--green-soft, #EBF5EE);
      color: var(--green, #2F6B3A);
    }
    .ain-tag.gen {
      background: var(--amber-soft, #FDF6E7);
      color: var(--amber, #8A5A00);
    }
    .ain-text {
      display: block;
    }
    .ain-meta {
      display: block;
      font-size: 11px;
      color: var(--i2);
      margin-top: 4px;
    }
    #ain-form {
      display: flex;
      gap: 6px;
      padding: 10px;
      border-top: 1px solid var(--l);
      background: var(--s);
    }
    #ain-input {
      flex: 1;
      padding: 8px 10px;
      border: 1px solid var(--l);
      border-radius: var(--radius-input, 4px);
      font: inherit;
      resize: none;
      height: 38px;
      background: var(--s);
      color: var(--i);
    }
    #ain-input:focus {
      outline: 2px solid var(--a);
      outline-offset: 0;
    }
    #ain-send {
      background: var(--a);
      color: #FFFFFF;
      border: 0;
      border-radius: var(--radius-input, 4px);
      padding: 0 14px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
    }
    #ain-send:disabled {
      opacity: 0.5;
      cursor: wait;
    }
    @media (max-width: 520px) {
      #ain-panel { right: 12px; bottom: 68px; }
      #ain-btn { right: 12px; bottom: 12px; }
    }
  `;

  function el(tag, attrs, text) {
    const e = document.createElement(tag);
    Object.assign(e, attrs || {});
    if (text) e.textContent = text;
    return e;
  }

  function pageContext() {
    try {
      if (typeof state === "object" && state) {
        const person = (state.people || []).find((p) => p.resident_id === state.selected);
        return { resident_id: state.selected, name: person ? person.name : null, role: state.role };
      }
    } catch (e) {}
    return { resident_id: null, name: null, role: null };
  }

  document.head.appendChild(el("style", {}, css));

  const btn = el("button", { id: "ain-btn", type: "button" });
  btn.append(el("span", { className: "pulse" }), "AI Nurse");
  const panel = el("div", { id: "ain-panel", role: "dialog" });
  panel.setAttribute("aria-label", "AI Nurse");
  const head = el("div", { id: "ain-head" });
  const top = el("div", { className: "top" });
  top.append(el("b", {}, "AI Nurse"), el("button", { id: "ain-close", type: "button" }, "Close"));
  const about = el("div", { id: "ain-about" });
  const model = el("select", { id: "ain-model", title: "AI model" });
  head.append(top, about, model);
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

  function showAbout() {
    const ctx = pageContext();
    const role = ctx.role ? ctx.role[0].toUpperCase() + ctx.role.slice(1) : null;
    about.textContent = ctx.name
      ? "About " + ctx.name + (role ? " · " + role : "")
      : "General questions · Fictional data only";
  }

  let loaded = false;
  async function loadModels() {
    loaded = true;
    model.replaceChildren(new Option("Loading models...", ""));
    try {
      const data = await (await fetch("/api/ask/models")).json();
      model.replaceChildren();
      btn.classList.toggle("off", !data.ollama_running);
      if (!data.ollama_running) {
        model.add(new Option("No models found", ""));
        addMsg("err", "The AI is offline. Start Ollama with: ollama serve");
        loaded = false;
        return;
      }
      for (const name of (data.models || [])) {
        const label = name === data.default ? name + " (recommended)" : name;
        model.add(new Option(label, name, false, name === data.default));
      }
    } catch (e) {
      model.replaceChildren(new Option("Server not reachable", ""));
      btn.classList.add("off");
      loaded = false;
    }
  }

  btn.addEventListener("click", () => {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) {
      showAbout();
      if (!loaded) loadModels();
      if (!msgs.children.length) addMsg("bot", "Kia ora, ask me about the selected resident's care. Answers are drawn from nurse-approved guidance. Always verify with the RN in charge.");
      input.focus();
    }
  });
  document.getElementById("ain-close").addEventListener("click", () => panel.classList.remove("open"));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (question.length === 0) return;
    const ctx = pageContext();
    showAbout();
    addMsg("user", question);
    input.value = "";
    send.disabled = true;
    const wait = addMsg("bot", "Reading notes on local model…");
    const started = Date.now();
    try {
      const headers = { "Content-Type": "application/json" };
      if (ctx.role) headers["X-Role"] = ctx.role;
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ question, model: model.value || null, resident_id: ctx.resident_id }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please ask a longer question");
      let tag = "General answer, not from approved guidance";
      if (data.grounded) tag = "From approved guidance" + (ctx.name ? " for " + ctx.name : "");
      else if (ctx.name) tag = "No approved guidance for " + ctx.name + " yet";
      wait.replaceChildren(
        el("span", { className: "ain-tag " + (data.grounded ? "ok" : "gen") }, tag),
        el("span", { className: "ain-text" }, data.answer)
      );
      let meta = data.model + " · " + ((Date.now() - started) / 1000).toFixed(1) + "s";
      if (data.sources && data.sources.length) meta += " · Sources: " + data.sources.join(", ");
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
