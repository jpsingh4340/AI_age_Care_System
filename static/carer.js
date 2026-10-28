// carer page - load residents, save tasks / vitals / concerns, show today's list

// the AI Nurse bubble reads this too
var state = { role: "carer", people: [], selected: null };

var STATUS_TEXT = { given: "Given", refused: "Refused", not_done: "Not done" };

function $(id) {
  return document.getElementById(id);
}

async function getJSON(url) {
  var res = await fetch(url, { headers: { "X-Role": "carer" } });
  if (!res.ok) return null;
  return await res.json();
}

async function postJSON(url, data) {
  var res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Role": "carer" },
    body: JSON.stringify(data),
  });
  var body = await res.json();
  if (!res.ok) {
    // pydantic errors come back as a list
    var msg = typeof body.detail === "string" ? body.detail : "Please check what you typed";
    throw new Error(msg);
  }
  return body;
}

function showMsg(id, text, type) {
  $(id).textContent = text;
  $(id).className = "msg " + type;
}

function fillSelect(select, items) {
  select.innerHTML = "";
  items.forEach(function (item) {
    select.add(new Option(item, item));
  });
}

function carerName() {
  var name = $("carer").value.trim();
  if (name === "" || name.length === 1) {
    alert("Please type your name first");
    $("carer").focus();
    return null;
  }
  localStorage.setItem("carerName", name);
  return name;
}

function timeOnly(iso) {
  return iso.slice(11, 16);
}

// ---------- load ----------

async function loadPage() {
  $("carer").value = localStorage.getItem("carerName") || "";

  var opts = await getJSON("/api/carer/options");
  fillSelect($("task"), opts.tasks);
  fillSelect($("ctype"), opts.concern_types);

  var people = await getJSON("/api/residents");
  if (!people) {
    $("guide").textContent = "Can't reach the server.";
    return;
  }
  state.people = people;
  var sel = $("resident");
  people.forEach(function (p) {
    sel.add(new Option(p.name, p.resident_id));
  });
  sel.addEventListener("change", changeResident);
  changeResident();
}

function changeResident() {
  var id = $("resident").value;
  // resident ids can be numbers, keep the same type as the api
  var person = state.people.find(function (p) { return String(p.resident_id) === id; });
  state.selected = person.resident_id;
  $("todayName").textContent = person.name;
  loadToday();
  loadGuide();
}

async function loadToday() {
  var data = await getJSON("/api/carer/today?resident_id=" + encodeURIComponent(state.selected));
  var rows = [];
  data.tasks.forEach(function (t) {
    rows.push({ time: t.created_at, what: t.task + " - " + STATUS_TEXT[t.status], cls: t.status, by: t.carer });
  });
  data.vitals.forEach(function (v) {
    var parts = [];
    if (v.pulse) parts.push("Pulse " + v.pulse);
    if (v.systolic && v.diastolic) parts.push("BP " + v.systolic + "/" + v.diastolic);
    if (v.temperature) parts.push("Temp " + v.temperature);
    if (v.spo2) parts.push("O2 " + v.spo2 + "%");
    rows.push({ time: v.created_at, what: "Vitals: " + parts.join(", "), cls: "", by: v.carer });
  });
  data.concerns.forEach(function (c) {
    rows.push({ time: c.created_at, what: "Concern (" + c.type + "): " + c.note, cls: "refused", by: c.carer });
  });
  rows.sort(function (a, b) { return a.time > b.time ? -1 : 1; });

  var body = $("todayRows");
  body.innerHTML = "";
  if (rows.length === 0) {
    var tr = body.insertRow();
    var td = tr.insertCell();
    td.colSpan = 3;
    td.textContent = "Nothing recorded yet today.";
    return;
  }
  rows.forEach(function (r) {
    var tr = body.insertRow();
    tr.insertCell().textContent = timeOnly(r.time);
    var what = tr.insertCell();
    var badge = document.createElement("span");
    badge.textContent = r.what;
    if (r.cls) badge.className = "tag-" + r.cls.replace("_", "-");
    what.appendChild(badge);
    tr.insertCell().textContent = r.by;
  });
}

async function loadGuide() {
  var box = $("guide");
  var g = await getJSON("/api/guidance/" + state.selected + "/approved");
  if (!g) {
    box.innerHTML = "<p class='small' style='color:#758a8a; font-style:italic;'>No approved guidance for this resident yet. An RN will prepare and approve instructions.</p>";
    return;
  }
  box.innerHTML = "";
  addList(box, "Signs to watch for", g.watch_for);
  addList(box, "Daily prevention steps", g.prevention);
  var by = document.createElement("div");
  by.className = "approved-footer";
  by.textContent = "Approved by " + g.approved_by + " · Clinical oversight";
  box.appendChild(by);
}

function addList(box, heading, lines) {
  if (!lines || lines.length === 0) return;
  var b = document.createElement("b");
  b.textContent = heading;
  var ul = document.createElement("ul");
  ul.className = "guide-list";
  lines.forEach(function (l) {
    var li = document.createElement("li");
    li.textContent = l.text;
    ul.appendChild(li);
  });
  box.appendChild(b);
  box.appendChild(ul);
}

// ---------- save buttons ----------

$("saveTask").addEventListener("click", async function () {
  var name = carerName();
  if (!name) return;
  var status = document.querySelector("input[name=status]:checked").value;
  try {
    await postJSON("/api/carer/tasks", {
      resident_id: String(state.selected), task: $("task").value, status: status, carer: name,
    });
    showMsg("taskMsg", "Saved: " + $("task").value + " - " + STATUS_TEXT[status], "ok");
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
      showMsg("vitalsMsg", "Saved. Some numbers are outside the usual range, please tell the nurse now.", "warn");
    } else {
      showMsg("vitalsMsg", "Vitals saved.", "ok");
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
  try {
    await postJSON("/api/carer/concerns", {
      resident_id: String(state.selected), type: $("ctype").value, note: $("cnote").value.trim(), carer: name,
    });
    showMsg("concernMsg", "Sent to the nurse.", "ok");
    $("cnote").value = "";
    loadToday();
  } catch (e) {
    showMsg("concernMsg", e.message, "err");
  }
});

loadPage();