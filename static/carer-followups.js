// Feature C: follow-ups the nurse sent after a camera alert, shown on the carer's "My shift" page.
// The carer ticks each one off with an optional note. The nurse sees it as done on the Camera page.
(function () {
  var current = null;

  function line(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  var ALERT_NAMES = { possible_fall: "Possible fall", no_movement: "No movement", high_cue: "Face check", medium_cue: "Face check" };

  async function loadFollowups(residentId) {
    current = residentId;
    var list = await getJSON("/api/vision/followups?resident_id=" + encodeURIComponent(residentId));
    if (residentId !== current) return;  // the carer already picked another resident
    var card = document.getElementById("followupCard");
    var box = document.getElementById("followups");
    list = list || [];
    card.hidden = list.length === 0;
    document.getElementById("followupCount").textContent = list.length + " to do";
    box.replaceChildren();
    list.forEach(function (f) {
      var item = line("div", "alert-box alert-warn");
      item.style.marginTop = "10px";
      item.append(line("strong", "", f.instruction));
      item.append(line("p", "sub-text", (ALERT_NAMES[f.alert_type] || "Alert") + " · from " + f.sent_by + " at " + (f.sent_at || "").slice(11, 16)));
      var note = line("input", "field");
      note.maxLength = 300;
      note.placeholder = "What you did (optional)";
      note.setAttribute("aria-label", "Note for the nurse");
      note.style.marginTop = "8px";
      var done = line("button", "btn btn-primary btn-sm", "Done");
      done.type = "button";
      done.style.marginTop = "8px";
      done.addEventListener("click", async function () {
        var name = carerName("noteMsg");
        if (!name) return;
        done.disabled = true;
        try {
          await postJSON("/api/vision/followups/" + f.id + "/done", { carer: name, note: note.value });
          if (window.showToast) window.showToast("Done. The nurse can see it now.");
          loadFollowups(current);
        } catch (error) {
          done.disabled = false;
          if (window.showToast) window.showToast(error.message, true);
        }
      });
      item.append(note, done);
      box.append(item);
    });
  }

  window.loadFollowups = loadFollowups;
})();
