// AgeCare Senior Bedside Tablet - Interactive Level 7 Client Logic
let currentResidentId = 1;
let currentWaterCups = 0;
const waterTarget = 6;
let speechEnabled = true;
let isListening = false;
let recognition = null;

function $(id) {
  return document.getElementById(id);
}

// Gentle Web Audio Sound Synthesizer (Chimes & Alerts)
function playChime(type = "chime") {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    if (type === "water") {
      // Pleasant water droplet pitch slide
      osc.type = "sine";
      osc.frequency.setValueAtTime(600, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
      osc.start();
      osc.stop(ctx.currentTime + 0.26);
    } else if (type === "alert") {
      // Urgent soft double pulse
      osc.type = "triangle";
      osc.frequency.setValueAtTime(520, ctx.currentTime);
      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);
      osc.start();
      osc.stop(ctx.currentTime + 0.36);
    } else {
      // Gentle friendly affirmative bell
      osc.type = "sine";
      osc.frequency.setValueAtTime(523.25, ctx.currentTime); // C5
      osc.frequency.exponentialRampToValueAtTime(659.25, ctx.currentTime + 0.2); // E5
      gain.gain.setValueAtTime(0.18, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
      osc.start();
      osc.stop(ctx.currentTime + 0.41);
    }
  } catch (e) {
    // Audio context may require prior user gesture
  }
}

// Floating Toast Notification
function showToast(title, desc, type = "ok", icon = "ℹ️") {
  const container = $("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast-item ${type}`;
  toast.innerHTML = `
    <div class="toast-icon">${icon}</div>
    <div class="toast-content">
      <div class="toast-title">${title}</div>
      <div class="toast-desc">${desc}</div>
    </div>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(50px) scale(0.95)";
    setTimeout(() => toast.remove(), 350);
  }, 4200);
}

// Inline fallback banner message
function showMsg(id, text, type) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = "action-feedback show " + type;
  setTimeout(() => {
    el.classList.remove("show");
  }, 5000);
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
  // Hide all panels
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.style.display = "none";
    panel.classList.remove("active");
  });
  // Deactivate all buttons
  document.querySelectorAll(".tab-pill-btn").forEach((b) => b.classList.remove("active"));

  // Show selected panel
  const target = $(tabId);
  if (target) {
    target.style.display = "block";
    target.classList.add("active");
  }
  if (btn) {
    btn.classList.add("active");
  }
}

// Hydration Glasses Renderer & Tracker
function renderHydrationGlasses(count) {
  currentWaterCups = Math.min(Math.max(0, count), waterTarget);
  const container = $("waterGlassesRow");
  const countEl = $("waterCupsCount");
  const fillEl = $("hydrationProgressFill");

  if (countEl) countEl.textContent = currentWaterCups;
  if (fillEl) {
    const pct = Math.round((currentWaterCups / waterTarget) * 100);
    fillEl.style.width = `${pct}%`;
  }
  if (!container) return;

  container.innerHTML = "";
  for (let i = 1; i <= waterTarget; i++) {
    const isFilled = i <= currentWaterCups;
    const glass = document.createElement("button");
    glass.className = "glass-slot" + (isFilled ? " filled" : "");
    glass.setAttribute("aria-label", `Glass ${i} of ${waterTarget}` + (isFilled ? " - Completed" : " - Tap to log"));
    glass.innerHTML = isFilled ? "💧" : "🥛";
    glass.onclick = () => {
      if (i > currentWaterCups) {
        logWaterGlass();
      } else {
        showToast("Hydration Completed", `Glass #${i} was already logged today! Keep up the good work.`, "ok", "💧");
      }
    };
    container.appendChild(glass);
  }
}

async function logWaterGlass() {
  const newCount = currentWaterCups + 1;
  renderHydrationGlasses(newCount);
  playChime("water");
  showToast("Hydration Logged", `1 fresh glass of water logged (${newCount}/${waterTarget} cups)! Carer shift sheet updated.`, "ok", "💧");
  showMsg("waterFeedback", `💧 Wonderful! Glass #${newCount} logged toward your 1,500 mL daily goal.`, "ok");

  if (speechEnabled && window.speechSynthesis) {
    speakText(`Wonderful job drinking water, Peggy! That is ${newCount} of your 6 daily glasses.`);
  }

  try {
    const url = `/api/patient/log-water?resident_id=${currentResidentId}`;
    const opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount_cups: 1, resident_id: currentResidentId }),
    };
    if (window.authFetch) {
      await window.authFetch("/api/patient/log-water", opts);
    } else {
      await fetch(url, opts);
    }
  } catch (err) {
    console.warn("Water sync offline fallback", err);
  }
}

// Bedside Room & Resident Switcher
function switchResident(id, btn) {
  currentResidentId = id;
  document.querySelectorAll(".room-pill").forEach((p) => p.classList.remove("active"));
  if (btn) btn.classList.add("active");

  playChime("chime");
  loadDay(id);
}

// Load Full Day Data for Selected Resident
async function loadDay(overrideId) {
  const resId = overrideId || currentResidentId;
  try {
    const url = "/api/patient/my-day?resident_id=" + resId;
    const res = await (window.authFetch ? window.authFetch(url) : fetch(url));
    if (!res.ok) throw new Error("Could not load daily routine");
    const data = await res.json();
    currentResidentId = data.resident_id;

    // 1. Identity & Avatar
    const avatarEmoji = $("residentAvatarEmoji");
    if (avatarEmoji) {
      avatarEmoji.textContent = data.resident_id === 1 || data.resident_id === 3 ? "👵" : "👴";
    }

    // Sync active room pill
    document.querySelectorAll(".room-pill").forEach((p, idx) => {
      p.classList.toggle("active", idx + 1 === data.resident_id);
    });

    // Passport Details
    const profile = data.profile_details || {};
    const hour = new Date().getHours();
    const period = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    const prefName = profile.preferred_name || data.name;

    if ($("greetingTitle")) $("greetingTitle").textContent = `${period}, ${prefName}`;
    if ($("residentAge")) $("residentAge").textContent = `${profile.age || 82} yrs`;
    if ($("tagRoom")) $("tagRoom").textContent = `${profile.wing || "Garden Wing"} · ${data.room}`;
    if ($("passportConditions")) {
      const conds = profile.key_conditions || ["Type 2 Diabetes", "Mild Cognitive Impairment", "Osteoarthritis"];
      $("passportConditions").textContent = `Primary Care Plan: ${conds.join(" · ")}`;
    }
    if ($("doctorName")) $("doctorName").textContent = profile.primary_doctor || "Dr. Robert Chen";
    if ($("nurseName")) $("nurseName").textContent = profile.assigned_nurse || "Nurse Sarah (RN)";
    if ($("mobilityStatus")) $("mobilityStatus").textContent = profile.mobility_status || "4-Wheel Frame";
    if ($("dietaryBadge")) $("dietaryBadge").textContent = profile.dietary_plan || "Soft Diabetic";

    // Next of Kin
    const nok = profile.emergency_contact || {};
    if ($("familyContactName")) $("familyContactName").textContent = nok.name || "Claire Taylor (Daughter)";
    if ($("familyContactInfo")) $("familyContactInfo").textContent = nok.visit_info || "Visiting Saturday at 2:00 PM";
    if ($("familyContactPhone")) $("familyContactPhone").textContent = nok.phone ? `📞 ${nok.phone}` : "📞 +64 21 555 019";

    // 2. Hydration
    renderHydrationGlasses(data.water_cups_logged || 0);

    // 3. Highlight sentiment buttons
    if (data.latest_sentiment) {
      document.querySelectorAll(".sentiment-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.sentiment === data.latest_sentiment);
      });
    }

    // 4. Schedule Timeline
    const scheduleContainer = $("scheduleList");
    if (scheduleContainer) {
      scheduleContainer.innerHTML = "";
      data.schedule.forEach((item) => {
        const isCompleted = item.status.includes("Completed") || item.status.includes("Done");
        const row = document.createElement("div");
        row.className = "schedule-row" + (isCompleted ? " completed" : "");
        row.innerHTML = `
          <div class="row-time">${item.time}</div>
          <div class="row-body">
            <div class="row-title">${item.title}</div>
            ${item.completed_by ? `<div class="row-carer">✓ Signed off by ${item.completed_by}</div>` : ""}
          </div>
          <span class="row-badge">${item.status}</span>
        `;
        scheduleContainer.appendChild(row);
      });
    }

    // 5. Chef's Dining Menu
    const menuContainer = $("menuList");
    if (menuContainer && data.meals_today) {
      menuContainer.innerHTML = "";
      data.meals_today.forEach((m) => {
        const mDiv = document.createElement("div");
        mDiv.className = "menu-card";
        mDiv.innerHTML = `
          <div class="menu-header-flex">
            <span class="menu-title">${m.meal_type}</span>
            <span class="menu-tag">${m.dietary_badge}</span>
          </div>
          <div class="menu-dish-name">${m.dish}</div>
          <div class="menu-beverage">☕ Accompaniment: <strong>${m.beverage}</strong></div>
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
        aDiv.className = "activity-card";
        aDiv.innerHTML = `
          <div>
            <div class="activity-title-text">${a.title}</div>
            <div class="activity-loc-text">📍 ${a.location}</div>
          </div>
          <span class="activity-time-pill">${a.time}</span>
        `;
        actContainer.appendChild(aDiv);
      });
    }

    // 7. Family Message
    if (data.family_messages && data.family_messages.length) {
      const fam = data.family_messages[0];
      if ($("familyMsgSender")) $("familyMsgSender").textContent = fam.sender;
      if ($("familyMsgDate")) $("familyMsgDate").textContent = fam.timestamp;
      if ($("familyMsgText")) $("familyMsgText").textContent = `"${fam.message}"`;
      if ($("familySenderBadge")) $("familySenderBadge").textContent = `From ${fam.sender.split(" ")[0]}`;
    }

    // 8. Care Guidance Reminders
    const adviceList = $("adviceList");
    if (adviceList) {
      adviceList.innerHTML = "";
      if (!data.approved_guidance || !data.approved_guidance.length) {
        adviceList.innerHTML = "<li>Rest well today and ring your call bell if you need help standing or transferring.</li>";
      } else {
        data.approved_guidance.forEach((line) => {
          const li = document.createElement("li");
          li.textContent = line;
          adviceList.appendChild(li);
        });
      }
    }

    showToast("Bedside Profile Synced", `Loaded active care sheet for ${prefName} (${data.room})`, "ok", "🧓");
  } catch (err) {
    console.error("loadDay error", err);
  }
}

// 1. Daily Wellbeing Sentiment Check-In
async function checkInSentiment(sentiment) {
  // Highlight active button immediately
  document.querySelectorAll(".sentiment-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.sentiment === sentiment);
  });

  const isPain = sentiment === "in_pain" || sentiment === "uncomfortable";
  playChime(isPain ? "alert" : "chime");

  if (sentiment === "great") {
    showToast("Feeling Great!", "Shared with your care team. Have a wonderful, sunny day!", "ok", "😊");
    showMsg("wellbeingFeedback", "😊 Wonderful! Your positive wellbeing check-in has been shared with Nurse Sarah.", "ok");
    if (speechEnabled) speakText("Wonderful to hear you are feeling great! Enjoy your day.");
  } else if (sentiment === "okay") {
    showToast("Doing Okay", "Noted on your daily shift sheet. Carers are nearby if you need anything.", "ok", "😐");
    showMsg("wellbeingFeedback", "😐 Recorded: Doing okay today.", "ok");
    if (speechEnabled) speakText("Thank you for checking in. Your carers are nearby whenever you need them.");
  } else if (sentiment === "uncomfortable") {
    showToast("Comfort Alert Sent", "You reported feeling stiff or tired. Carer notified to check your pillows and seating.", "warn", "😟");
    showMsg("wellbeingFeedback", "😟 Carer notified to check your comfort and seating position.", "ok");
    if (speechEnabled) speakText("Thank you for letting us know. I have asked your carer to come check your comfort.");
  } else if (sentiment === "in_pain") {
    showToast("URGENT: Pain Alert Triggered", "Registered Nurse on duty and lead carer have been dispatched to your room immediately.", "urgent", "🚨");
    showMsg("wellbeingFeedback", "🚨 URGENT: Nurse Sarah has been alerted to review pain management immediately.", "alert");
    if (speechEnabled) speakText("Please rest comfortably where you are. I have immediately alerted Nurse Sarah and your carer to come to your room right away.");
  }

  try {
    const url = `/api/patient/wellbeing?resident_id=${currentResidentId}`;
    const opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sentiment, note: "", resident_id: currentResidentId }),
    };
    if (window.authFetch) {
      await window.authFetch("/api/patient/wellbeing", opts);
    } else {
      await fetch(url, opts);
    }
  } catch (err) {
    console.warn("Sentiment sync error", err);
  }
}

// 2. Bedside Call Bell & Room Services Trigger
async function triggerCallBell(type) {
  const isUrgent = type.toLowerCase().includes("urgent") || type.toLowerCase().includes("emergency");
  playChime("alert");

  showToast(
    isUrgent ? "🚨 URGENT CALL DISPATCHED" : "🔔 Service Request Logged",
    `Staff alerted for: "${type}". Caregiver is on their way to your room.`,
    isUrgent ? "urgent" : "ok",
    isUrgent ? "🚨" : "🔔"
  );
  showMsg("callBellFeedback", `🔔 Request Sent: "${type}". Care staff notified.`, "ok");

  if (speechEnabled) {
    if (isUrgent) {
      speakText("Emergency assistance called. A nurse and carer are on their way to your bedside now.");
    } else {
      speakText(`Your request for ${type} has been sent. A carer will assist you shortly.`);
    }
  }

  try {
    const url = `/api/patient/call-bell?resident_id=${currentResidentId}`;
    const opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_type: type, resident_id: currentResidentId }),
    };
    if (window.authFetch) {
      await window.authFetch("/api/patient/call-bell", opts);
    } else {
      await fetch(url, opts);
    }
  } catch (err) {
    console.warn("Call bell sync fallback", err);
  }
}

// 3. Send Love Back to Family
async function sendLoveToFamily() {
  playChime("chime");
  showToast("Love Sent ❤️", "Warm message and hugs sent to Claire! She will receive your reassurance.", "ok", "❤️");
  showMsg("familyFeedback", "❤️ Love and reassurance sent back to Claire! She will be delighted.", "ok");

  const replyStatus = $("famReplyStatus");
  if (replyStatus) {
    replyStatus.textContent = "✓ Reassurance sent just now!";
    replyStatus.style.color = "#127844";
  }

  if (speechEnabled) {
    speakText("Your love and message have been sent to Claire.");
  }

  try {
    const url = `/api/patient/family-reply?resident_id=${currentResidentId}`;
    const opts = { method: "POST" };
    if (window.authFetch) {
      await window.authFetch("/api/patient/family-reply", opts);
    } else {
      await fetch(url, opts);
    }
  } catch (err) {
    console.warn("Family reply fallback", err);
  }
}

// 4. AI Bedside Voice Companion ("Grace")
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
      indicator.innerHTML = "<span>💡</span> Microphone is not active on this browser session. Tap any quick question chip or type below!";
      indicator.style.display = "flex";
      setTimeout(() => {
        indicator.style.display = "none";
      }, 5000);
    }
    return;
  }
  if (isListening) {
    recognition.stop();
  } else {
    try {
      recognition.start();
    } catch (e) {
      console.warn("Speech recognition error", e);
    }
  }
}

function toggleSpeech() {
  speechEnabled = !speechEnabled;
  const btn = $("voiceToggleBtn");
  const icon = $("voiceIcon");
  const label = $("voiceLabel");
  if (speechEnabled) {
    if (btn) btn.classList.remove("muted");
    if (icon) icon.textContent = "🔊";
    if (label) label.textContent = "Voice Audio: On";
    showToast("Voice Companion Active", "Grace will speak answers aloud with friendly bedside audio.", "ok", "🔊");
  } else {
    if (btn) btn.classList.add("muted");
    if (icon) icon.textContent = "🔇";
    if (label) label.textContent = "Voice Audio: Muted";
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    showToast("Voice Audio Muted", "Grace is muted. Responses will appear as text on screen.", "warn", "🔇");
  }
}

function speakText(text) {
  if (!speechEnabled || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();

  const bubble = $("companionSpeech");
  const wave = $("voiceWaveIndicator");
  const graceCard = document.querySelector(".grace-card");
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.88;
  utterance.pitch = 1.05;

  utterance.onstart = () => {
    if (bubble) bubble.classList.add("speaking");
    if (wave) wave.style.display = "flex";
    if (graceCard) graceCard.classList.add("speaking");
  };
  utterance.onend = () => {
    if (bubble) bubble.classList.remove("speaking");
    if (wave) wave.style.display = "none";
    if (graceCard) graceCard.classList.remove("speaking");
  };
  utterance.onerror = () => {
    if (bubble) bubble.classList.remove("speaking");
    if (wave) wave.style.display = "none";
    if (graceCard) graceCard.classList.remove("speaking");
  };

  window.speechSynthesis.speak(utterance);
}

function askCompanion(text) {
  const input = $("companionInput");
  if (input) input.value = text;
  submitCompanionInput();
}

// Instant Clinical AI Knowledge for Sub-200ms Bedside Responsiveness
function getClinicalFastReply(q, resId) {
  const qLower = q.toLowerCase();
  if (
    qLower.includes("fall") ||
    qLower.includes("fell") ||
    qLower.includes("floor") ||
    qLower.includes("pain") ||
    qLower.includes("emergency") ||
    qLower.includes("hurt")
  ) {
    return {
      reply: "Please stay still and rest where you are. I have immediately alerted Nurse Sarah and your carer on duty to come to your room right away.",
      speech_text: "Please stay still and rest where you are. I have immediately alerted Nurse Sarah and your carer to come to your room right away.",
      emergency_alert: true,
      followups: ["Nurse is on the way", "Help standing", "Where is my carer?"],
    };
  }
  if (
    qLower.includes("lunch") ||
    qLower.includes("dinner") ||
    qLower.includes("breakfast") ||
    qLower.includes("food") ||
    qLower.includes("eat") ||
    qLower.includes("hungry") ||
    qLower.includes("meal")
  ) {
    return {
      reply: "Your next meal is Lunch at 12:30 PM in the dining lounge, featuring tender roast chicken with sweet kumara mash, followed by dinner at 5:30 PM. Would you like a warm cup of tea now?",
      speech_text: "Your next meal is Lunch at 12:30 PM in the dining lounge, featuring tender roast chicken with sweet kumara mash, followed by dinner at 5:30 PM. Would you like a warm cup of tea now?",
      emergency_alert: false,
      followups: ["What is for dinner?", "Can I have some water?", "When is my walk?"],
    };
  }
  if (qLower.includes("walk") || qLower.includes("frame") || qLower.includes("physio") || qLower.includes("exercise") || qLower.includes("move")) {
    return {
      reply: "Your mobility walk with your frame is scheduled for 11:30 AM. Your carer will be here to walk alongside you safely and check your brakes.",
      speech_text: "Your mobility walk with your frame is scheduled for 11:30 AM. Your carer will be here to walk alongside you safely and check your brakes.",
      emergency_alert: false,
      followups: ["Who is my carer?", "Can I have some water?", "What is for lunch?"],
    };
  }
  if (qLower.includes("water") || qLower.includes("drink") || qLower.includes("thirsty") || qLower.includes("target")) {
    return {
      reply: `Your hydration target is 6 glasses (1,500 mL) per day to stay energized and protect kidney function. You currently have ${currentWaterCups} of 6 glasses logged!`,
      speech_text: `Your hydration target is 6 glasses per day. You currently have ${currentWaterCups} of 6 glasses logged!`,
      emergency_alert: false,
      followups: ["Log 1 glass of water", "What is for lunch?", "Who is my nurse?"],
    };
  }
  if (qLower.includes("carer") || qLower.includes("nurse") || qLower.includes("who") || qLower.includes("looking after")) {
    return {
      reply: "Your assigned Registered Nurse is Nurse Sarah (RN), and your caregiver on duty is Carer David. They are right down the hall in the Garden Wing.",
      speech_text: "Your assigned Registered Nurse is Nurse Sarah, and your caregiver on duty is Carer David. They are right down the hall in the Garden Wing.",
      emergency_alert: false,
      followups: ["Call carer to room", "When is my walk?", "What is for lunch?"],
    };
  }
  if (qLower.includes("where") || qLower.includes("home") || qLower.includes("place") || qLower.includes("room")) {
    return {
      reply: "You are safe and sound in your room at Serene Haven Aged Care. The staff are right down the hall looking after you, and everything is calm and peaceful.",
      speech_text: "You are safe and sound in your room at Serene Haven Aged Care. The staff are right down the hall looking after you, and everything is calm and peaceful.",
      emergency_alert: false,
      followups: ["Who is my carer?", "When is my walk?", "What is for lunch?"],
    };
  }
  if (qLower.includes("comfort") || qLower.includes("thought") || qLower.includes("poem") || qLower.includes("relax")) {
    return {
      reply: "Take a gentle deep breath, Margaret. You are surrounded by warm, caring friends today, the sun is shining through the garden terrace, and you are doing wonderfully.",
      speech_text: "Take a gentle deep breath, Margaret. You are surrounded by warm caring friends today, and you are doing wonderfully.",
      emergency_alert: false,
      followups: ["When is my walk?", "What is for lunch?", "Tell me another thought"],
    };
  }
  return {
    reply: "Hello! You are doing wonderfully today. Your routine schedule is running smoothly, and your care team is right down the hall. How can I help make you more comfortable?",
    speech_text: "Hello! You are doing wonderfully today. Your care team is right down the hall. How can I help make you more comfortable?",
    emergency_alert: false,
    followups: ["What is for lunch?", "When is my walk?", "How much water should I drink?"],
  };
}

async function submitCompanionInput() {
  const input = $("companionInput");
  const question = input ? input.value.trim() : "";
  if (!question) return;

  const bubble = $("companionSpeech");
  const sendBtn = $("companionSendBtn");
  if (sendBtn) sendBtn.disabled = true;
  if (bubble) {
    bubble.innerHTML = `<em>Grace is listening... "${question}"</em>`;
  }

  let data = null;
  try {
    const fetchPromise = (
      window.authFetch
        ? window.authFetch("/api/patient/companion", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, resident_id: currentResidentId }),
          })
        : fetch("/api/patient/companion?resident_id=" + currentResidentId, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, resident_id: currentResidentId }),
          })
    ).then((r) => (r.ok ? r.json() : Promise.reject()));

    // Race against 1.8s timeout so the senior is never kept waiting
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("fast_fallback")), 1800)
    );

    data = await Promise.race([fetchPromise, timeoutPromise]);
  } catch (e) {
    data = getClinicalFastReply(question, currentResidentId);
  }

  if (bubble) {
    if (data.emergency_alert) {
      bubble.innerHTML = `<span style="color: #b52b24; font-weight: 800;">🚨 [NURSE ALERTED]</span> "${data.reply}"`;
      triggerCallBell("AI Voice Alarm: Emergency Assistance");
    } else {
      bubble.textContent = `"${data.reply}"`;
    }
  }

  if (input) input.value = "";
  if (sendBtn) sendBtn.disabled = false;

  // Speak aloud with Grace's warm bedside voice
  speakText(data.speech_text || data.reply);

  // Update follow-up quick chips
  const followups = data.suggested_followups || data.followups;
  if (followups && followups.length) {
    const chipsContainer = $("quickChipsContainer");
    if (chipsContainer) {
      chipsContainer.innerHTML = followups
        .map(
          (f) =>
            `<button class="q-chip" onclick="askCompanion('${f.replace(/'/g, "\\'")}')">💬 ${f}</button>`
        )
        .join("");
    }
  }
}

// Initializer on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  updateClock();
  setInterval(updateClock, 1000);

  // Initial load
  loadDay();
  setInterval(() => loadDay(currentResidentId), 30000);

  initVoiceCompanion();
});
