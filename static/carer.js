// Carer shift sheet: pick a resident, save care records, read approved guidance.
var state = { role: "carer", people: [], selected: null };

var STATUS_TEXT = { given: "Done", refused: "Refused", not_done: "Not done" };

function $(id) {
  return document.getElementById(id);
}

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function getJSON(url) {
  var fn = window.authFetch || fetch;
  var res = await fn(url, { headers: { "X-Role": "carer" } });
  if (!res.ok) return null;
  return await res.json();
}

async function postJSON(url, data) {
  var fn = window.authFetch || fetch;
  var res = await fn(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Role": "carer" },
    body: JSON.stringify(data),
  });
  var body = await res.json();
  if (!res.ok) {
    var msg = typeof body.detail === "string" ? body.detail : "Please check what you entered.";
    throw new Error(msg);
  }
  return body;
}

function showMsg(id, text, type) {
  var box = $(id);
  if (!box) return;
  box.textContent = text;
  var cls = "text-sm ";
  if (type === "ok") cls += "alert-success";
  else if (type === "warn") cls += "alert-warn";
  else cls += "alert-danger";
  box.className = cls;
  if (window.showToast) window.showToast(text, type === "err");
}

function fillSelect(select, items) {
  select.replaceChildren();
  items.forEach(function (item) {
    select.add(new Option(item, item));
  });
}

function carerName(msgId) {
  var name = $("carer").value.trim();
  if (name.length < 2) {
    var fallback = localStorage.getItem("agecare_name") || "";
    if (fallback) {
      $("carer").value = fallback;
      return fallback;
    }
    showMsg(msgId, "Type your name in 'Carer on duty' first.", "err");
    $("carer").focus();
    return null;
  }
  localStorage.setItem("carerName", name);
  return name;
}

function timeOnly(iso) {
  return (iso || "").slice(11, 16);
}

function roomOf(p) {
  return "Room " + (100 + Number(p.resident_id));
}

function renderPills() {
  var wrap = $("residentPills");
  if (!wrap) return;
  wrap.replaceChildren();
  state.people.forEach(function (p) {
    var btn = el("button", "pill", p.name + " · " + roomOf(p));
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(String(p.resident_id) === String(state.selected)));
    btn.addEventListener("click", function () {
      $("resident").value = String(p.resident_id);
      changeResident();
    });
    wrap.appendChild(btn);
  });
}

async function loadPage() {
  $("carer").value = localStorage.getItem("carerName") || localStorage.getItem("agecare_name") || "";

  var opts = await getJSON("/api/carer/options");
  if (opts) {
    fillSelect($("task"), opts.tasks || []);
    fillSelect($("ctype"), opts.concern_types || []);
  }

  var people = await getJSON("/api/residents");
  if (!people) {
    $("residentPills").replaceChildren(el("p", "alert-box alert-danger", "Could not reach the server. Check that the backend is running."));
    $("guide").textContent = "";
    return;
  }
  state.people = people;
  var sel = $("resident");
  sel.replaceChildren();
  people.forEach(function (p) {
    sel.add(new Option(p.name + " (" + roomOf(p) + ")", p.resident_id));
  });
  sel.addEventListener("change", changeResident);
  changeResident();
}

function changeResident() {
  var id = $("resident").value;
  var person = state.people.find(function (p) { return String(p.resident_id) === String(id); }) || state.people[0];
  if (!person) return;
  state.selected = person.resident_id;
  $("todayName").textContent = person.name;
  $("recordName").textContent = person.name;
  $("residentConditions").textContent = (person.conditions || []).join(", ");
  ["taskMsg", "vitalsMsg", "concernMsg"].forEach(function (m) {
    $(m).textContent = "";
    $(m).className = "text-sm";
  });
  renderPills();
  loadToday();
  loadGuide();
}

async function loadToday() {
  var data = await getJSON("/api/carer/today?resident_id=" + encodeURIComponent(state.selected));
  if (!data) return;
  var rows = [];
  (data.tasks || []).forEach(function (t) {
    rows.push({ time: t.created_at, what: t.task + ": " + (STATUS_TEXT[t.status] || t.status), status: t.status, by: t.carer });
  });
  (data.vitals || []).forEach(function (v) {
    var parts = [];
    if (v.pulse) parts.push("Pulse " + v.pulse);
    if (v.systolic && v.diastolic) parts.push("BP " + v.systolic + "/" + v.diastolic);
    if (v.temperature) parts.push("Temp " + v.temperature + "°C");
    if (v.spo2) parts.push("SpO2 " + v.spo2 + "%");
    rows.push({ time: v.created_at, what: "Vital signs: " + parts.join(", "), status: "vitals", by: v.carer });
  });
  (data.concerns || []).forEach(function (c) {
    rows.push({ time: c.created_at, what: "Concern (" + c.type + "): " + c.note, status: "concern", by: c.carer });
  });
  rows.sort(function (a, b) { return a.time > b.time ? -1 : 1; });

  var body = $("todayRows");
  body.replaceChildren();
  if (rows.length === 0) {
    var td = body.insertRow().insertCell();
    td.colSpan = 3;
    td.className = "empty";
    td.textContent = "Nothing recorded yet today. Use the form to add the first task.";
    return;
  }
  rows.forEach(function (r) {
    var tr = body.insertRow();
    var tdTime = tr.insertCell();
    tdTime.className = "text-mono";
    tdTime.textContent = timeOnly(r.time);

    var tdWhat = tr.insertCell();
    tdWhat.textContent = r.what;
    if (r.status === "concern") tdWhat.style.color = "var(--red)";
    else if (r.status === "refused" || r.status === "not_done") tdWhat.style.color = "var(--amber)";

    var tdBy = tr.insertCell();
    tdBy.className = "sub-text";
    tdBy.style.whiteSpace = "nowrap";
    tdBy.textContent = r.by;
  });
}

async function loadGuide() {
  var box = $("guide");
  var g = await getJSON("/api/guidance/" + state.selected + "/approved");
  box.replaceChildren();
  if (!g) {
    box.appendChild(el("p", "empty", "No approved guidance for this resident yet. Ask the nurse on duty if you are unsure."));
    return;
  }
  addList(box, "Signs to watch for", g.watch_for, true);
  addList(box, "Every day", g.prevention, false);
  box.appendChild(el("p", "sub-text", "Approved by " + g.approved_by));
}

function addList(box, heading, lines, first) {
  if (!lines || lines.length === 0) return;
  var label = el("p", "section-label", heading);
  if (first) label.style.marginTop = "0";
  box.appendChild(label);
  var ul = el("ul", "bullets");
  lines.forEach(function (l) {
    ul.appendChild(el("li", "", l.text));
  });
  box.appendChild(ul);
}

$("saveTask").addEventListener("click", async function () {
  var name = carerName("taskMsg");
  if (!name) return;
  var statusRadio = document.querySelector("input[name=status]:checked");
  var status = statusRadio ? statusRadio.value : "given";
  try {
    await postJSON("/api/carer/tasks", {
      resident_id: String(state.selected), task: $("task").value, status: status, carer: name,
    });
    showMsg("taskMsg", "Saved: " + $("task").value + " (" + (STATUS_TEXT[status] || status) + ")", "ok");
    loadToday();
  } catch (e) {
    showMsg("taskMsg", e.message, "err");
  }
});

$("saveVitals").addEventListener("click", async function () {
  var name = carerName("vitalsMsg");
  if (!name) return;
  var data = { resident_id: String(state.selected), carer: name };
  ["pulse", "systolic", "diastolic", "temperature", "spo2"].forEach(function (f) {
    data[f] = $(f).value === "" ? null : Number($(f).value);
  });
  try {
    var res = await postJSON("/api/carer/vitals", data);
    if (res.tell_nurse) {
      showMsg("vitalsMsg", "Saved. A reading is outside the usual range. Tell the nurse now.", "warn");
    } else {
      showMsg("vitalsMsg", "Vital signs saved.", "ok");
    }
    ["pulse", "systolic", "diastolic", "temperature", "spo2"].forEach(function (f) { $(f).value = ""; });
    loadToday();
  } catch (e) {
    showMsg("vitalsMsg", e.message, "err");
  }
});

$("saveConcern").addEventListener("click", async function () {
  var name = carerName("concernMsg");
  if (!name) return;
  var note = $("cnote").value.trim();
  if (note.length < 3) {
    showMsg("concernMsg", "Write a short note about what you noticed.", "err");
    $("cnote").focus();
    return;
  }
  try {
    await postJSON("/api/carer/concerns", {
      resident_id: String(state.selected), type: $("ctype").value, note: note, carer: name,
    });
    showMsg("concernMsg", "Sent to the nurse on duty.", "ok");
    $("cnote").value = "";
    loadToday();
  } catch (e) {
    showMsg("concernMsg", e.message, "err");
  }
});

loadPage();
