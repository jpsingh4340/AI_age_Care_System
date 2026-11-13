// Carer shift sheet: pick a resident, save care records, read approved guidance.
var state = { role: "carer", people: [], selected: null, schedule: [] };

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

function nowHHMM() {
  var d = new Date();
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
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
    if ($("task")) fillSelect($("task"), opts.tasks || []);
    if ($("ctype")) fillSelect($("ctype"), opts.concern_types || []);
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
  ["noteMsg", "vitalsMsg", "concernMsg"].forEach(function (m) {
    if ($(m)) {
      $(m).textContent = "";
      $(m).className = "text-sm";
    }
  });
  renderPills();
    if (window.loadFollowups) window.loadFollowups(person.resident_id);  // Feature C: nurse follow-ups
  loadGuide();
  loadSchedule().then(loadToday);
}

async function loadToday() {
  var results = await Promise.all([
    getJSON("/api/carer/today?resident_id=" + encodeURIComponent(state.selected)),
    getJSON("/api/carer/notes?resident_id=" + encodeURIComponent(state.selected)),
  ]);
  var data = results[0];
  if (!data) return;
  var rows = [];
  (results[1] || []).forEach(function (n) {
    rows.push({ time: n.created_at, what: "Note: " + n.text, status: "note", by: n.carer });
  });
  (state.schedule || []).forEach(function (s) {
    if (s.done_at) rows.push({ time: s.done_at, what: "Care plan: " + s.task + " done", status: "plan", by: s.done_by });
  });
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
    else if (r.status === "plan") tdWhat.style.color = "var(--green)";
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

// ---------- Today's care plan (set by the nurse) ----------
async function loadSchedule() {
  var box = $("schedule");
  var items = await getJSON("/api/schedule?resident_id=" + encodeURIComponent(state.selected));
  state.schedule = items || [];
  box.replaceChildren();
  if (!items) {
    box.appendChild(el("p", "empty", "Could not load the care plan."));
    return;
  }
  var done = items.filter(function (i) { return i.done_at; }).length;
  $("planCount").textContent = items.length ? done + " of " + items.length + " done" : "";
  if (!items.length) {
    box.appendChild(el("p", "empty", "No care plan set for this resident yet. The nurse adds daily tasks on the Schedule page."));
    return;
  }
  items.forEach(function (item) {
    var row = el("label", "check-row");
    var sw = el("input", "switch");
    sw.type = "checkbox";
    sw.setAttribute("role", "switch");
    sw.checked = Boolean(item.done_at);
    var locked = !item.can_tick && !item.done_at;
    sw.disabled = locked;
    var text = el("span");
    var title = el("span", "task", (item.time ? item.time + "  " : "") + item.task);
    var overdue = !item.done_at && item.time && item.time < nowHHMM();
    if (overdue) {
      title.appendChild(document.createTextNode(" "));
      title.appendChild(el("span", "badge badge-amber", "Overdue"));
    }
    if (item.medicine) {
      title.appendChild(document.createTextNode(" "));
      title.appendChild(el("span", "badge badge-med", "Medicine"));
    }
    text.appendChild(title);
    var meta = item.done_at
      ? "Done by " + item.done_by + " at " + timeOnly(item.done_at)
      : locked
        ? (item.meds || []).some(function (m) { return m.route.indexOf("Injection") === 0; })
          ? "Includes an injection, so only a nurse can tick this. Tell the nurse."
          : "Only a nurse or a carer signed off for medicines can tick this. Tell the nurse."
        : item.note || "Not done yet";
    text.appendChild(el("span", "meta", meta));
    if (item.meds && item.meds.length) {
      var ul = el("ul", "med-list");
      item.meds.forEach(function (m) {
        var li = el("li");
        li.appendChild(el("strong", "", m.name));
        li.appendChild(document.createTextNode(" " + m.dose + " "));
        li.appendChild(el("span", "how", "· " + m.route + (m.instructions ? " · " + m.instructions : "")));
        ul.appendChild(li);
      });
      text.appendChild(ul);
      if (item.meds_checked_by) text.appendChild(el("span", "meta", "Checked against the chart by " + item.meds_checked_by));
    }
    if (locked) row.style.cursor = "default";
    sw.addEventListener("change", async function () {
      sw.disabled = true;
      try {
        var fn = window.authFetch || fetch;
        var res = await fn("/api/schedule/" + item.id + "/done", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ done: sw.checked }),
        });
        if (!res.ok) {
          var body = await res.json().catch(function () { return {}; });
          throw new Error(typeof body.detail === "string" ? body.detail : "Could not save. Please try again.");
        }
        if (window.showToast) window.showToast(item.task + (sw.checked ? " done" : " marked not done"));
      } catch (e) {
        sw.checked = !sw.checked;
        if (window.showToast) window.showToast(e.message, true);
      }
      await loadSchedule();
      loadToday();
    });
    row.append(sw, text);
    box.appendChild(row);
  });
}

$("saveNote").addEventListener("click", async function () {
  var text = $("noteText").value.trim();
  if (text.length < 2) {
    showMsg("noteMsg", "Write a short note first.", "err");
    $("noteText").focus();
    return;
  }
  try {
    await postJSON("/api/carer/notes", { resident_id: Number(state.selected), text: text });
    showMsg("noteMsg", "Note saved.", "ok");
    $("noteText").value = "";
    loadToday();
  } catch (e) {
    showMsg("noteMsg", e.message, "err");
  }
});

if ($("saveTask")) {
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
}

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
