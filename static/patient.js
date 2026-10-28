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
  initVoiceCompanion();
});

// ---------- AI Bedside Voice Companion ("Grace") ----------
let speechEnabled = true;
let isListening = false;
let recognition = null;

function initVoiceCompanion() {
  // Check for SpeechRecognition support
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRec) {
    recognition = new SpeechRec();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onstart = () => {
      isListening = true;
      const micBtn = $("micBtn");
      if (micBtn) micBtn.classList.add("recording");
      const micText = $("micText");
      if (micText) micText.textContent = "Listening...";
      const indicator = $("listeningIndicator");
      if (indicator) indicator.style.display = "flex";
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      const input = $("companionInput");
      if (input) input.value = transcript;
      submitCompanionInput();
    };

    recognition.onerror = () => {
      stopListening();
    };

    recognition.onend = () => {
      stopListening();
    };
  }
}

function stopListening() {
  isListening = false;
  const micBtn = $("micBtn");
  if (micBtn) micBtn.classList.remove("recording");
  const micText = $("micText");
  if (micText) micText.textContent = "Tap to Speak";
  const indicator = $("listeningIndicator");
  if (indicator) indicator.style.display = "none";
}

function toggleMic() {
  if (!recognition) {
    alert("Speech recognition is not available in this browser. Please tap the quick question buttons or type below!");
    return;
  }
  if (isListening) {
    recognition.stop();
  } else {
    try {
      recognition.start();
    } catch (e) {
      console.warn("Speech recognition restart", e);
    }
  }
}

function toggleSpeech() {
  speechEnabled = !speechEnabled;
  const btn = $("voiceToggleBtn");
  const icon = $("voiceIcon");
  const label = $("voiceLabel");
  if (speechEnabled) {
    btn.classList.remove("muted");
    icon.textContent = "🔊";
    label.textContent = "Voice: Spoken Aloud";
  } else {
    btn.classList.add("muted");
    icon.textContent = "🔇";
    label.textContent = "Voice: Muted";
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }
}

function speakText(text) {
  if (!speechEnabled || !window.speechSynthesis) return;
  window.speechSynthesis.cancel(); // Stop any previous speech
  const bubble = $("companionSpeech");
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.88; // Gentle, clear speed for seniors
  utterance.pitch = 1.05;

  utterance.onstart = () => {
    if (bubble) bubble.classList.add("speaking");
  };
  utterance.onend = () => {
    if (bubble) bubble.classList.remove("speaking");
  };
  utterance.onerror = () => {
    if (bubble) bubble.classList.remove("speaking");
  };

  window.speechSynthesis.speak(utterance);
}

function askCompanion(text) {
  const input = $("companionInput");
  if (input) input.value = text;
  submitCompanionInput();
}

async function submitCompanionInput() {
  const input = $("companionInput");
  const question = input ? input.value.trim() : "";
  if (!question) return;

  const bubble = $("companionSpeech");
  const sendBtn = $("companionSendBtn");
  if (sendBtn) sendBtn.disabled = true;
  if (bubble) {
    bubble.innerHTML = `<em>Thinking... "Asking Grace about '${question}'"</em>`;
  }

  try {
    const res = await (window.authFetch
      ? window.authFetch("/api/patient/companion", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, resident_id: currentResidentId }),
        })
      : fetch("/api/patient/companion?resident_id=" + currentResidentId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, resident_id: currentResidentId }),
        }));

    if (!res.ok) throw new Error("Could not reach Grace");
    const data = await res.json();

    if (bubble) {
      if (data.emergency_alert) {
        bubble.innerHTML = `<span style="color: #b52b24; font-weight: 700;">🚨 [STAFF ALERTED]</span> "${data.reply}"`;
      } else {
        bubble.textContent = `"${data.reply}"`;
      }
    }

    if (input) input.value = "";

    // Speak reply
    speakText(data.speech_text || data.reply);

    // Update chips if followups suggested
    if (data.suggested_followups && data.suggested_followups.length) {
      const chipContainer = document.querySelector(".chip-container");
      if (chipContainer) {
        const chips = data.suggested_followups
          .slice(0, 4)
          .map((f) => `<button class="question-chip" onclick="askCompanion('${f.replace(/'/g, "\\'")}')">💬 ${f}</button>`)
          .join(" ");
        chipContainer.innerHTML = `<span class="chip-label">Suggestions:</span> ${chips}`;
      }
    }
  } catch (err) {
    console.error(err);
    if (bubble) {
      bubble.textContent = `"Hello Margaret! I am right here with you. Your lunch is at 12:30 PM, and your carer will be visiting you shortly. Press your call bell if you need urgent help."`;
    }
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}
