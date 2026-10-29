// Carer shift sheet - load assigned residents, save care records, view approved guidance.
var state = { role: "carer", people: [], selected: null };

var STATUS_TEXT = { given: "Given", refused: "Refused", not_done: "Not done" };

function $(id) {
  return document.getElementById(id);
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
    var msg = typeof body.detail === "string" ? body.detail : "Please check your entries.";
    throw new Error(msg);
  }
  return body;
}

function showMsg(id, text, type) {
  var el = $(id);
  if (!el) return;
  el.textContent = text;
  var cls = "text-sm ";
  if (type === "ok") cls += "alert-success";
  else if (type === "warn") cls += "alert-warn";
  else cls += "alert-danger";
  el.className = cls;
  if (window.showToast) window.showToast(text, type === "err");
}

function fillSelect(select, items) {
  select.replaceChildren();
  items.forEach(function (item) {
    select.add(new Option(item, item));
  });
}

function carerName() {
  var name = $("carer").value.trim();
  if (name === "" || name.length < 2) {
    var fallback = localStorage.getItem("agecare_name") || "";
    if (fallback) {
      $("carer").value = fallback;
      return fallback;
    }
    alert("Please type your name in the 'Carer on duty' field.");
    $("carer").focus();
    return null;
  }
  localStorage.setItem("carerName", name);
  return name;
}

function timeOnly(iso) {
  return (iso || "").slice(11, 16);
}

function renderPills() {
  var wrap = $("residentPills");
  if (!wrap) return;
  wrap.replaceChildren();
  state.people.forEach(function (p) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pill";
    btn.setAttribute("aria-pressed", String(String(p.resident_id) === String(state.selected)));
    btn.textContent = p.name + " · Room " + (100 + Number(p.resident_id));
    btn.addEventListener("click", function () {
      $("resident").value = String(p.resident_id);
      changeResident();
    });
    wrap.appendChild(btn);
  });
}

async function loadPage() {
  var savedName = localStorage.getItem("carerName") || localStorage.getItem("agecare_name") || "Priya P.";
  $("carer").value = savedName;

  var opts = await getJSON("/api/carer/options");
  if (opts) {
    fillSelect($("task"), opts.tasks || []);
    fillSelect($("ctype"), opts.concern_types || []);
  }

  var people = await getJSON("/api/residents");
  if (!people) {
    $("guide").textContent = "Could not connect to the server.";
    return;
  }
  state.people = people;
  var sel = $("resident");
  sel.replaceChildren();
  people.forEach(function (p) {
    sel.add(new Option(p.name + " (Room " + (100 + Number(p.resident_id)) + ")", p.resident_id));
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
  var condEl = $("residentConditions");
  if (condEl) condEl.textContent = (person.conditions || []).join(" · ");
  renderPills();
  loadToday();
  loadGuide();
}

async function loadToday() {
  var data = await getJSON("/api/carer/today?resident_id=" + encodeURIComponent(state.selected));
  if (!data) return;
  var rows = [];
  (data.tasks || []).forEach(function (t) {
    rows.push({ time: t.created_at, what: t.task + " — " + (STATUS_TEXT[t.status] || t.status), status: t.status, by: t.carer });
  });
  (data.vitals || []).forEach(function (v) {
    var parts = [];
    if (v.pulse) parts.push("Pulse " + v.pulse + " bpm");
    if (v.systolic && v.diastolic) parts.push("BP " + v.systolic + "/" + v.diastolic);
    if (v.temperature) parts.push("Temp " + v.temperature + "°C");
    if (v.spo2) parts.push("SpO2 " + v.spo2 + "%");
    rows.push({ time: v.created_at, what: "Vitals: " + parts.join(", "), status: "vitals", by: v.carer });
  });
  (data.concerns || []).forEach(function (c) {
    rows.push({ time: c.created_at, what: "Concern (" + c.type + "): " + c.note, status: "concern", by: c.carer });
  });
  rows.sort(function (a, b) { return a.time > b.time ? -1 : 1; });

  var body = $("todayRows");
  body.replaceChildren();
  if (rows.length === 0) {
    var tr = body.insertRow();
    var td = tr.insertCell();
    td.colSpan = 3;
    td.className = "text-muted";
    td.textContent = "Nothing recorded yet today for this resident.";
    return;
  }
  rows.forEach(function (r) {
    var tr = body.insertRow();
    var tdTime = tr.insertCell();
    tdTime.className = "text-mono";
    tdTime.textContent = timeOnly(r.time);

    var tdWhat = tr.insertCell();
    var span = document.createElement("span");
    span.textContent = r.what;
    if (r.status === "concern") {
      span.className = "badge badge-red";
      span.style.fontWeight = "600";
    } else if (r.status === "refused" || r.status === "not_done") {
      span.className = "badge badge-amber";
    }
    tdWhat.appendChild(span);

    var tdBy = tr.insertCell();
    tdBy.className = "text-sm text-muted";
    tdBy.textContent = r.by;
  });
}

async function loadGuide() {
  var box = $("guide");
  var g = await getJSON("/api/guidance/" + state.selected + "/approved");
  box.replaceChildren();
  if (!g) {
    var p = document.createElement("p");
    p.className = "text-muted";
    p.textContent = "No approved guidance for this resident yet. A Registered Nurse will review and approve care guidance.";
    box.appendChild(p);
    return;
  }

  addList(box, "Signs to watch for", g.watch_for);
  addList(box, "Daily prevention steps", g.prevention);

  var by = document.createElement("div");
  by.className = "sub-text";
  by.style.marginTop = "10px";
  by.textContent = "Approved by " + g.approved_by;
  box.appendChild(by);
}

function addList(box, heading, lines) {
  if (!lines || lines.length === 0) return;
  var b = document.createElement("div");
  b.style.fontWeight = "600";
  b.style.color = "var(--ink)";
  b.style.marginTop = "8px";
  b.textContent = heading;
  box.appendChild(b);

  var ul = document.createElement("ul");
  ul.style.margin = "4px 0 10px";
  ul.style.paddingLeft = "18px";
  lines.forEach(function (l) {
    var li = document.createElement("li");
    li.textContent = l.text;
    ul.appendChild(li);
  });
  box.appendChild(ul);
}

// Save handlers
$("saveTask").addEventListener("click", async function () {
  var name = carerName();
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
  var name = carerName();
  if (!name) return;
  var data = { resident_id: String(state.selected), carer: name };
  ["pulse", "systolic", "diastolic", "temperature", "spo2"].forEach(function (f) {
    data[f] = $(f).value === "" ? null : Number($(f).value);
  });
  try {
    var res = await postJSON("/api/carer/vitals", data);
    if (res.tell_nurse) {
      showMsg("vitalsMsg", "Saved. Outside usual range — please tell the nurse immediately.", "warn");
    } else {
      showMsg("vitalsMsg", "Vitals saved successfully.", "ok");
    }
    ["pulse", "systolic", "diastolic", "temperature", "spo2"].forEach(function (f) { $(f).value = ""; });
    loadToday();
  } catch (e) {
    showMsg("vitalsMsg", e.message, "err");
  }
});

$("saveConcern").addEventListener("click", async function () {
  var name = carerName();
  if (!name) return;
  var note = $("cnote").value.trim();
  if (note.length < 3) {
    showMsg("concernMsg", "Please write a brief note about what you observed.", "err");
    $("cnote").focus();
    return;
  }
  try {
    await postJSON("/api/carer/concerns", {
      resident_id: String(state.selected), type: $("ctype").value, note: note, carer: name,
    });
    showMsg("concernMsg", "Concern sent to the nurse on duty.", "ok");
    $("cnote").value = "";
    loadToday();
  } catch (e) {
    showMsg("concernMsg", e.message, "err");
  }
});

loadPage();
