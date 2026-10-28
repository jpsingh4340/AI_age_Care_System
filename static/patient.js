// Patient / Resident Portal Client Logic
let currentResidentId = 1;

function $(id) {
  return document.getElementById(id);
}

function showMsg(id, text, type) {
  const el = $(id);
  el.textContent = text;
  el.className = "feedback-msg show " + type;
  setTimeout(() => {
    el.classList.remove("show");
  }, 6000);
}

async function loadDay() {
  try {
    const res = await (window.authFetch ? window.authFetch("/api/patient/my-day") : fetch("/api/patient/my-day"));
    if (!res.ok) throw new Error("Could not load daily routine");
    const data = await res.json();
    currentResidentId = data.resident_id;

    // Greeting & Header
    const hour = new Date().getHours();
    const period = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    $("greetingTitle").textContent = `${period}, ${data.name}`;
    $("roomNumber").textContent = data.room.replace("Room ", "");
    $("todayDate").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

    // Highlight previous sentiment if any
    if (data.latest_sentiment) {
      document.querySelectorAll(".feeling-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.sentiment === data.latest_sentiment);
      });
    }

    // Schedule list
    const scheduleContainer = $("scheduleList");
    scheduleContainer.innerHTML = "";
    data.schedule.forEach((item) => {
      const isCompleted = item.status.includes("Completed");
      const div = document.createElement("div");
      div.className = "schedule-item" + (isCompleted ? " completed" : "");
      div.innerHTML = `
        <div class="schedule-time">${item.time}</div>
        <div class="schedule-title">
          <div>${item.title}</div>
          ${item.completed_by ? `<div style="font-size: 13px; color: #1a7f4c; font-weight: 500;">${item.completed_by}</div>` : ""}
        </div>
        <div class="schedule-status">${item.status}</div>
      `;
      scheduleContainer.appendChild(div);
    });

    // Approved Guidance
    const adviceList = $("adviceList");
    adviceList.innerHTML = "";
    if (!data.approved_guidance.length) {
      adviceList.innerHTML = "<li>Rest well today and let your carers know if you need any help.</li>";
    } else {
      data.approved_guidance.forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        adviceList.appendChild(li);
      });
    }
  } catch (err) {
    console.error(err);
  }
}

async function checkInSentiment(sentiment) {
  document.querySelectorAll(".feeling-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.sentiment === sentiment);
  });

  try {
    const res = await (window.authFetch
      ? window.authFetch("/api/patient/wellbeing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sentiment, note: "" }),
        })
      : fetch("/api/patient/wellbeing?resident_id=" + currentResidentId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sentiment, note: "" }),
        }));
    const data = await res.json();
    if (data.alert_triggered) {
      showMsg("wellbeingFeedback", "❤️ Thank you for letting us know. We've notified your nurse and carer to check on you right away.", "alert");
    } else {
      showMsg("wellbeingFeedback", "😊 Wonderful to hear! Have a lovely day.", "ok");
    }
  } catch (err) {
    showMsg("wellbeingFeedback", "Could not send check-in right now.", "alert");
  }
}

async function triggerCallBell(type) {
  try {
    const res = await (window.authFetch
      ? window.authFetch("/api/patient/call-bell", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request_type: type }),
        })
      : fetch("/api/patient/call-bell?resident_id=" + currentResidentId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request_type: type }),
        }));
    if (res.ok) {
      showMsg("callBellFeedback", `🔔 Assistance Requested (${type})! Carer and nurse on duty have been alerted.`, "ok");
    } else {
      showMsg("callBellFeedback", "Could not send call bell. Please press your bedside physical buzzer.", "alert");
    }
  } catch (err) {
    showMsg("callBellFeedback", "Please press your bedside physical buzzer.", "alert");
  }
}

// Auto-refresh daily schedule every 30 seconds so completed carer tasks show in real time
document.addEventListener("DOMContentLoaded", () => {
  loadDay();
  setInterval(loadDay, 30000);
});
