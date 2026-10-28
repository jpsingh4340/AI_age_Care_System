// Client-side authentication and role-based access guard
(function () {
  const token = localStorage.getItem("agecare_token");
  const role = localStorage.getItem("agecare_role");
  const name = localStorage.getItem("agecare_name");
  const path = window.location.pathname.toLowerCase();

  // Pages requiring Nurse role
  const NURSE_PAGES = ["/nurse", "/guidance", "/ocr"];
  // Pages requiring Carer role
  const CARER_PAGES = ["/carer"];
  // Pages requiring Patient role
  const PATIENT_PAGES = ["/patient"];

  function redirect(url) {
    window.location.replace(url);
  }

  // Check page access
  if (NURSE_PAGES.some((p) => path === p || path.startsWith(p + "/"))) {
    if (!token) {
      redirect("/login?next=" + encodeURIComponent(path));
      return;
    }
    if (role !== "nurse") {
      const dest = role === "patient" ? "/patient" : "/carer";
      alert("Access Denied: This clinical section requires Registered Nurse (RN) credentials.");
      redirect(dest);
      return;
    }
  } else if (CARER_PAGES.some((p) => path === p || path.startsWith(p + "/"))) {
    if (!token) {
      redirect("/login?next=" + encodeURIComponent(path));
      return;
    }
    if (role === "patient") {
      redirect("/patient");
      return;
    }
  } else if (PATIENT_PAGES.some((p) => path === p || path.startsWith(p + "/"))) {
    if (!token) {
      redirect("/login?next=" + encodeURIComponent(path));
      return;
    }
  }

  // Global authenticated fetch helper
  window.authFetch = async function (url, options) {
    options = options || {};
    options.headers = options.headers || {};
    if (token) {
      options.headers["Authorization"] = "Bearer " + token;
      options.headers["X-Session-Token"] = token;
      options.headers["X-Role"] = role || "";
    }
    return fetch(url, options);
  };

  // Global logout helper
  window.logout = async function () {
    if (token) {
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "Authorization": "Bearer " + token, "X-Session-Token": token }
        });
      } catch (e) {
        // ignore network error on logout
      }
    }
    localStorage.removeItem("agecare_session");
    localStorage.removeItem("agecare_token");
    localStorage.removeItem("agecare_role");
    localStorage.removeItem("agecare_name");
    redirect("/login");
  };

  // Auto-inject logged in profile badge into sidebar if present
  document.addEventListener("DOMContentLoaded", function () {
    if (!token) return;
    const side = document.querySelector(".rail, .side");
    if (!side) return;

    // Create user profile snippet
    const userBox = document.createElement("div");
    userBox.style.cssText = "margin-top:auto; padding:12px; background:rgba(255,255,255,0.08); border-radius:10px; margin-bottom:12px; font-size:12.5px;";
    userBox.innerHTML = `
      <div style="color:#b2edd9; font-weight:700; margin-bottom:2px; display:flex; align-items:center; justify-content:space-between;">
        <span>${role === 'nurse' ? '🩺 Nurse' : role === 'patient' ? '🧓 Resident' : '📋 Carer'}</span>
        <button onclick="logout()" style="background:transparent; border:none; color:#f6a8a3; font-size:11.5px; font-weight:600; cursor:pointer; text-decoration:underline; padding:0;">Sign Out</button>
      </div>
      <div style="color:#ffffff; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${name || 'Staff Member'}</div>
    `;

    // Insert above foot / switch-card
    const foot = side.querySelector(".foot, .side-note, .switch-card");
    if (foot) {
      side.insertBefore(userBox, foot);
    } else {
      side.appendChild(userBox);
    }
  });
})();
