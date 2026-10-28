// Patient / Resident Portal Client Logic - Comprehensive Bedside Tablet
let currentResidentId = 1;
let currentWaterCups = 0;
const waterTarget = 6;

function $(id) {
  return document.getElementById(id);
}

function showMsg(id, text, type) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = "feedback-msg show " + type;
  setTimeout(() => {
    el.classList.remove("show");
  }, 6000);
}

// Live Digital Clock
function updateClock() {
  const clockEl = $("liveClock");
  if (!clockEl) return;
  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const dateStr = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  clockEl.textContent = `${timeStr} · ${dateStr}`;
}

// Right Tab Switcher
function switchRightTab(tabId, btn) {
  document.querySelectorAll(".tab-content").forEach((tc) => {
    tc.style.display = "none";
    tc.classList.remove("active");
  });
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));

  const targetTab = $(tabId);
  if (targetTab) {
    targetTab.style.display = "block";
    targetTab.classList.add("active");
  }
  if (btn) btn.classList.add("active");
}

// Hydration Glasses Renderer
function renderHydrationGlasses(count) {
  currentWaterCups = count;
  const container = $("waterGlassesRow");
  const countEl = $("waterCupsCount");
  if (countEl) countEl.textContent = count;
  if (!container) return;

  container.innerHTML = "";
  for (let i = 1; i <= waterTarget; i++) {
    const isFilled = i <= count;
    const glass = document.createElement("div");
    glass.className = "water-glass-icon" + (isFilled ? " filled" : "");
    glass.innerHTML = isFilled ? "💧" : "🥛";
    glass.title = `Glass ${i} of ${waterTarget}` + (isFilled ? " (Drank)" : " (Pending)");
    container.appendChild(glass);
  }
}

async function logWaterGlass() {
  try {
    const res = await (window.authFetch
      ? window.authFetch("/api/patient/log-water", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ amount_cups: 1 }),
        })
      : fetch("/api/patient/log-water?resident_id=" + currentResidentId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ amount_cups: 1 }),
        }));

    if (res.ok) {
      renderHydrationGlasses(currentWaterCups + 1);
      showMsg("waterFeedback", "💧 Wonderful! 1 glass of water logged to your hydration goal and synced to your carer.", "ok");
      // Gentle voice encouragement if voice enabled
      if (speechEnabled && window.speechSynthesis) {
        speakText("Good job drinking water, Peggy! Staying hydrated keeps you energized.");
      }
    }
  } catch (err) {
    showMsg("waterFeedback", "Could not log water right now.", "alert");
  }
}

async function sendLoveToFamily() {
  try {
    const res = await (window.authFetch
      ? window.authFetch("/api/patient/family-reply", { method: "POST" })
      : fetch("/api/patient/family-reply?resident_id=" + currentResidentId, { method: "POST" }));
    if (res.ok) {
      showMsg("familyFeedback", "❤️ Love and warm hugs sent back to Claire! She will be delighted.", "ok");
      if (speechEnabled) {
        speakText("Your love and message have been sent to Claire.");
      }
    }
  } catch (err) {
    showMsg("familyFeedback", "Could not send message.", "alert");
  }
function switchResident(id, btn) {
  currentResidentId = id;
  document.querySelectorAll(".room-pill").forEach(p => p.classList.remove("active"));
  if (btn) btn.classList.add("active");
  loadDay(id);
}

async function loadDay(overrideId) {
  const resId = overrideId || currentResidentId;
  try {
    const url = "/api/patient/my-day?resident_id=" + resId;
    const res = await (window.authFetch ? window.authFetch(url) : fetch(url));
    if (!res.ok) throw new Error("Could not load daily routine");
    const data = await res.json();
    currentResidentId = data.resident_id;

    // Switch avatar emoji
    const avatarEmoji = $("residentAvatarEmoji");
    if (avatarEmoji) {
      avatarEmoji.textContent = (data.resident_id === 1 || data.resident_id === 3) ? "👵" : "👴";
    }

    // Sync active room pill
    document.querySelectorAll(".room-pill").forEach((p, idx) => {
      p.classList.toggle("active", (idx + 1) === data.resident_id);
    });

    // 1. Identity & Passport Profile
    const profile = data.profile_details || {};
    const hour = new Date().getHours();
    const period = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    const prefName = profile.preferred_name || data.name;
    $("greetingTitle").textContent = `${period}, ${prefName}`;
    if ($("topRoomNum")) $("topRoomNum").textContent = data.room.replace("Room ", "");
    if ($("residentAge")) $("residentAge").textContent = `${profile.age || 82} yrs`;
    if ($("profileWing")) $("profileWing").textContent = `${profile.wing || data.room} · Resident #${data.resident_id}`;
    if ($("doctorName")) $("doctorName").textContent = profile.primary_doctor || "Dr. Robert Chen";
    if ($("nurseName")) $("nurseName").textContent = profile.assigned_nurse || "Nurse Sarah (RN)";
    if ($("mobilityStatus")) $("mobilityStatus").textContent = profile.mobility_status || "Walking Frame";
    if ($("dietaryBadge")) $("dietaryBadge").textContent = profile.dietary_plan || "Soft Diet";

    // Next of Kin
    const nok = profile.emergency_contact || {};
    if ($("familyContactName")) $("familyContactName").textContent = nok.name || "Claire Taylor (Daughter)";
    if ($("familyContactInfo")) $("familyContactInfo").textContent = nok.visit_info || "Scheduled visit: Saturday";

    // 2. Hydration
    renderHydrationGlasses(data.water_cups_logged || 0);

    // 3. Highlight previous sentiment if any
    if (data.latest_sentiment) {
      document.querySelectorAll(".feeling-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.sentiment === data.latest_sentiment);
      });
    }

    // 4. Schedule list
    const scheduleContainer = $("scheduleList");
    if (scheduleContainer) {
      scheduleContainer.innerHTML = "";
      data.schedule.forEach((item) => {
        const isCompleted = item.status.includes("Completed");
        const div = document.createElement("div");
        div.className = "schedule-item" + (isCompleted ? " completed" : "");
        div.innerHTML = `
          <div class="schedule-time">${item.time}</div>
          <div class="schedule-title">
            <div>${item.title}</div>
            ${item.completed_by ? `<div style="font-size: 13px; color: #1a7f4c; font-weight: 500;">✓ ${item.completed_by}</div>` : ""}
          </div>
          <div class="schedule-status">${item.status}</div>
        `;
        scheduleContainer.appendChild(div);
      });
    }

    // 5. Chef's Daily Menu
    const menuContainer = $("menuList");
    if (menuContainer && data.meals_today) {
      menuContainer.innerHTML = "";
      data.meals_today.forEach((m) => {
        const mDiv = document.createElement("div");
        mDiv.className = "menu-card-item";
        mDiv.innerHTML = `
          <div class="menu-header">
            <span class="menu-type">${m.meal_type}</span>
            <span class="menu-badge">${m.dietary_badge}</span>
          </div>
          <div class="menu-dish">${m.dish}</div>
          <div class="menu-bev">☕ Served with: <strong>${m.beverage}</strong></div>
        `;
        menuContainer.appendChild(mDiv);
      });
    }

    // 6. Social Activities
    const actContainer = $("activitiesList");
    if (actContainer && data.activities_today) {
      actContainer.innerHTML = "";
      data.activities_today.forEach((a) => {
        const aDiv = document.createElement("div");
        aDiv.className = "activity-card-item";
        aDiv.innerHTML = `
          <div>
            <div class="activity-title">${a.title}</div>
            <div class="activity-loc">📍 ${a.location}</div>
          </div>
          <div class="activity-time">${a.time}</div>
        `;
        actContainer.appendChild(aDiv);
      });
    }

    // 7. Family Messages
    if (data.family_messages && data.family_messages.length) {
      const fam = data.family_messages[0];
      if ($("familyMsgSender")) $("familyMsgSender").textContent = fam.sender;
      if ($("familyMsgDate")) $("familyMsgDate").textContent = fam.timestamp;
      if ($("familyMsgText")) $("familyMsgText").textContent = `"${fam.message}"`;
    }

    // 8. Approved Guidance
    const adviceList = $("adviceList");
    if (adviceList) {
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
      if (speechEnabled) speakText("Thank you for letting us know, Peggy. I have notified Nurse Sarah and your carer right away.");
    } else {
      showMsg("wellbeingFeedback", "😊 Wonderful to hear! Have a lovely, peaceful day.", "ok");
      if (speechEnabled) speakText("Wonderful to hear! Have a lovely day, Peggy.");
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
      if (speechEnabled) speakText("Your call for assistance has been sent. A carer is on their way to your room.");
    } else {
      showMsg("callBellFeedback", "Could not send call bell. Please press your bedside physical buzzer.", "alert");
    }
  } catch (err) {
    showMsg("callBellFeedback", "Please press your bedside physical buzzer.", "alert");
  }
}

// ---------- AI Bedside Voice Companion ("Grace") ----------
let speechEnabled = true;
let isListening = false;
let recognition = null;

function initVoiceCompanion() {
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
  const indicator = $("listeningIndicator");
  if (!recognition) {
    if (indicator) {
      indicator.innerHTML = "<span>💡</span> Microphone is not supported on this browser/connection. You can tap the quick questions or type below!";
      indicator.style.display = "flex";
      setTimeout(() => { indicator.style.display = "none"; }, 5000);
    }
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
  window.speechSynthesis.cancel();
  const bubble = $("companionSpeech");
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.88;
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
    bubble.innerHTML = `<em>Grace is thinking... "Answering '${question}'"</em>`;
  }

  function getFastReply(q, resId) {
    const qLower = q.toLowerCase();
    if (qLower.includes("fall") || qLower.includes("fell") || qLower.includes("floor") || qLower.includes("pain") || qLower.includes("emergency") || qLower.includes("hurt")) {
      return {
        reply: "Please stay still and rest where you are. I have immediately alerted Nurse Sarah and your carer on duty to come to your room right away.",
        speech_text: "Please stay still and rest where you are. I have immediately alerted Nurse Sarah and your carer to come to your room right away.",
        emergency_alert: true,
        suggested_followups: ["Nurse is notified", "Stay comfortable", "Help is on the way"]
      };
    }
    if (qLower.includes("lunch") || qLower.includes("dinner") || qLower.includes("breakfast") || qLower.includes("food") || qLower.includes("eat") || qLower.includes("hungry") || qLower.includes("meal")) {
      return {
        reply: "Your next meal is Lunch at 12:30 PM in the dining lounge, featuring tender roast chicken with sweet kumara mash, followed by dinner at 5:30 PM. Would you like a warm cup of tea now?",
        speech_text: "Your next meal is Lunch at 12:30 PM in the dining lounge, featuring tender roast chicken with sweet kumara mash, followed by dinner at 5:30 PM. Would you like a warm cup of tea now?",
        emergency_alert: false,
        suggested_followups: ["What is for dinner?", "Can I have a drink?", "When is my walk?"]
      };
    }
    if (qLower.includes("walk") || qLower.includes("frame") || qLower.includes("physio") || qLower.includes("exercise") || qLower.includes("move")) {
      return {
        reply: "Your mobility walk with your frame is scheduled for 11:30 AM. Your carer will be here to walk alongside you safely and check your brakes.",
        speech_text: "Your mobility walk with your frame is scheduled for 11:30 AM. Your carer will be here to walk alongside you safely and check your brakes.",
        emergency_alert: false,
        suggested_followups: ["What is for lunch?", "Who is my carer?", "Where am I?"]
      };
    }
    if (qLower.includes("where") || qLower.includes("home") || qLower.includes("time") || qLower.includes("place") || qLower.includes("room")) {
      return {
        reply: "You are safe and sound in your room at AgeCare Haven. The staff are right down the hall looking after you, and everything is calm and peaceful.",
        speech_text: "You are safe and sound in your room at AgeCare Haven. The staff are right down the hall looking after you, and everything is calm and peaceful.",
        emergency_alert: false,
        suggested_followups: ["What is for lunch?", "Who is my carer?", "Can I have some water?"]
      };
    }
    return {
      reply: "Hello! You are doing wonderfully today. Your schedule is running on time, and your care team is right down the hall. How can I help make you more comfortable?",
      speech_text: "Hello! You are doing wonderfully today. Your schedule is running on time, and your care team is right down the hall. How can I help make you more comfortable?",
      emergency_alert: false,
      suggested_followups: ["What is for lunch?", "When is my walk?", "Can I have a cup of tea?"]
    };
  }

  let data = null;
  try {
    const fetchPromise = (window.authFetch
      ? window.authFetch("/api/patient/companion", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, resident_id: currentResidentId }),
        })
      : fetch("/api/patient/companion?resident_id=" + currentResidentId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, resident_id: currentResidentId }),
        })).then(r => r.ok ? r.json() : Promise.reject());

    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("fast_fallback")), 2200)
    );

    data = await Promise.race([fetchPromise, timeoutPromise]);
  } catch (e) {
    data = getFastReply(question, currentResidentId);
    if (data.emergency_alert) {
      triggerCallBell("AI Companion Emergency Alarm");
    }
  }

  if (bubble) {
    if (data.emergency_alert) {
      bubble.innerHTML = `<span style="color: #b52b24; font-weight: 700;">🚨 [STAFF ALERTED]</span> "${data.reply}"`;
    } else {
      bubble.textContent = `"${data.reply}"`;
    }
  }

  if (input) input.value = "";
  if (sendBtn) sendBtn.disabled = false;

  // Speak aloud
  speakText(data.speech_text || data.reply);

  // Update followup chips
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
}

// Initializer
document.addEventListener("DOMContentLoaded", () => {
  updateClock();
  setInterval(updateClock, 1000);
  loadDay();
  setInterval(loadDay, 30000);
  initVoiceCompanion();
});
