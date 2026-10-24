// AI Nurse chat bubble. Add to any page with one script tag.
// On the dashboard it reads the selected resident and role, so answers use that resident's approved guidance.
(function () {
  const css = `
    #ain-btn, #ain-panel { --a: var(--accent, #0a7c73); --s: var(--surface, #fff); --i: var(--ink, #0f1f1e);
      --i2: var(--ink2, #44595a); --l: var(--line, #d9e0de); --b: var(--bg, #edf0ee); --r: var(--rail, #0c3b3a);
      font-family: "Schibsted Grotesk", system-ui, "Segoe UI", Arial, sans-serif; }
    #ain-btn { position: fixed; right: 22px; bottom: 22px; z-index: 9999; background: var(--r); color: #fff;
      border: 1px solid rgba(255,255,255,.14); border-radius: 999px; padding: 12px 20px 12px 16px; font-size: 14.5px;
      font-weight: 600; display: flex; align-items: center; gap: 9px; cursor: pointer;
      box-shadow: 0 10px 28px -10px rgba(12,59,58,.55); transition: transform .2s, box-shadow .2s; }
    #ain-btn:hover { transform: translateY(-2px); box-shadow: 0 14px 32px -10px rgba(12,59,58,.65); }
    #ain-btn .pulse { width: 9px; height: 9px; border-radius: 50%; background: #5ccb8b; box-shadow: 0 0 0 3px rgba(92,203,139,.25); }
    #ain-btn.off .pulse { background: #f2766e; box-shadow: 0 0 0 3px rgba(242,118,110,.25); }
    #ain-panel { position: fixed; right: 22px; bottom: 82px; z-index: 9999; width: 380px; max-width: calc(100vw - 32px);
      height: 540px; max-height: calc(100vh - 110px); background: var(--s); color: var(--i); border: 1px solid var(--l);
      border-radius: 18px; box-shadow: 0 24px 60px -20px rgba(0,0,0,.35); display: none; flex-direction: column;
      font-size: 14.5px; line-height: 1.5; overflow: hidden; }
    #ain-panel.open { display: flex; animation: ain-in .22s ease-out; }
    @keyframes ain-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
    #ain-head { padding: 14px 16px 12px; background: var(--r); color: #fff; }
    #ain-head .top { display: flex; justify-content: space-between; align-items: center; }
    #ain-head b { font-size: 16px; font-weight: 600; letter-spacing: -.01em; }
    #ain-about { font-size: 12.5px; color: rgba(255,255,255,.78); margin: 2px 0 10px; }
    #ain-close { background: rgba(255,255,255,.12); border: 0; color: #fff; font-size: 12.5px; border-radius: 8px;
      padding: 4px 10px; cursor: pointer; }
    #ain-model { width: 100%; padding: 7px 9px; border: 1px solid rgba(255,255,255,.22); border-radius: 10px; font: inherit;
      font-size: 13.5px; background: rgba(255,255,255,.1); color: #fff; }
    #ain-model option { color: #0f1f1e; }
    #ain-msgs { flex: 1; overflow-y: auto; padding: 14px; background: var(--b); }
    .ain-msg { margin-bottom: 10px; padding: 9px 12px; border-radius: 14px; white-space: pre-wrap; max-width: 88%;
      background: var(--s); border: 1px solid var(--l); }
    .ain-user { background: #0a7c73; border-color: transparent; color: #fff; margin-left: auto; border-bottom-right-radius: 4px; }
    .ain-bot { border-bottom-left-radius: 4px; }
    .ain-err { background: var(--bad-soft, #fce8e6); color: var(--bad, #b3261e); border-color: transparent; }
    .ain-tag { display: inline-block; font-size: 11.5px; font-weight: 600; border-radius: 6px; padding: 0 7px; margin-bottom: 5px; }
    .ain-tag.ok { background: var(--good-soft, #e3f3e9); color: var(--good, #1f7a4a); }
    .ain-tag.gen { background: var(--warn-soft, #fff1d6); color: var(--warn, #9a5700); }
    .ain-text { display: block; }
    .ain-meta { display: block; font-size: 11.5px; color: var(--i2); margin-top: 6px; }
    #ain-form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--l); background: var(--s); }
    #ain-input { flex: 1; padding: 9px 11px; border: 1px solid var(--l); border-radius: 12px; font: inherit; resize: none;
      height: 42px; background: var(--s); color: var(--i); }
    #ain-input:focus { outline: 2px solid var(--a); outline-offset: 0; }
    #ain-send { background: #0a7c73; color: #fff; border: 0; border-radius: 12px; padding: 0 16px; font-weight: 600; cursor: pointer; }
    #ain-send:disabled { opacity: .55; cursor: wait; }
    @media (max-width: 520px) { #ain-panel { right: 16px; bottom: 76px; } #ain-btn { right: 16px; bottom: 16px; } }
    @media (prefers-reduced-motion: reduce) { #ain-panel.open { animation: none; } #ain-btn { transition: none; } }
  `;

  function el(tag, attrs, text) {
    const e = document.createElement(tag);
    Object.assign(e, attrs || {});
    if (text) e.textContent = text;
    return e;
  }

  // the dashboard keeps its data in a global called state
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
      : "General questions · fake data only";
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
      for (const name of data.models) {
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
      if (!msgs.children.length) addMsg("bot", "Hi, ask me about the selected resident's care. I answer from the nurse-approved guidance. Always check with the RN in charge.");
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
    const wait = addMsg("bot", "Thinking... on CPU this can take a little while.");
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