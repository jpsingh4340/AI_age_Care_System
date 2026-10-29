// Client-side authentication, strict role guard, and shared prototype topbar
(function () {
  const HOME_BY_ROLE = {
    carer: "/carer",
    nurse: "/nurse",
    manager: "/manager",
    family: "/family",
  };

  const ALLOWED_ROLES_BY_PATH = {
    "/carer": ["carer", "nurse"],
    "/nurse": ["nurse"],
    "/guidance": ["nurse"],
    "/ocr": ["nurse"],
    "/vision": ["nurse"],
    "/ask": ["carer", "nurse"],
    "/manager": ["manager"],
    "/family": ["family"],
  };

  const ROLE_LABELS = {
    carer: "Carer",
    nurse: "Nurse",
    manager: "Manager",
    family: "Family",
  };

  const token = localStorage.getItem("agecare_token") || "";
  const role = (localStorage.getItem("agecare_role") || "").toLowerCase();
  const fullName = localStorage.getItem("agecare_name") || "";
  const username = localStorage.getItem("agecare_username") || "";
  const residentId = localStorage.getItem("agecare_resident_id") || "";
  const path = window.location.pathname.toLowerCase();

  function redirect(url) {
    window.location.replace(url);
  }

  // Check if current page requires authentication and specific role
  for (const [routePrefix, allowedRoles] of Object.entries(ALLOWED_ROLES_BY_PATH)) {
    if (path === routePrefix || path.startsWith(routePrefix + "/")) {
      if (!token || !role) {
        redirect("/login?next=" + encodeURIComponent(path));
        return;
      }
      if (!allowedRoles.includes(role)) {
        const dest = HOME_BY_ROLE[role] || "/login";
        redirect(dest);
        return;
      }
      break;
    }
  }

  // Global authenticated fetch helper
  window.authFetch = async function (url, options) {
    options = options || {};
    options.headers = options.headers || {};
    const curToken = localStorage.getItem("agecare_token") || token;
    const curRole = localStorage.getItem("agecare_role") || role;
    if (curToken) {
      options.headers["Authorization"] = "Bearer " + curToken;
      options.headers["X-Session-Token"] = curToken;
    }
    if (curRole) {
      options.headers["X-Role"] = curRole;
    }
    return fetch(url, options);
  };

  // Global toast notification helper
  window.showToast = function (text, isError) {
    let host = document.getElementById("toastHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "toastHost";
      host.className = "toast-host";
      host.setAttribute("aria-live", "polite");
      document.body.appendChild(host);
    }
    const item = document.createElement("div");
    item.className = "toast" + (isError ? " err" : "");
    item.textContent = text;
    host.appendChild(item);
    setTimeout(function () {
      item.remove();
    }, 3500);
  };

  // Global logout helper
  window.logout = async function () {
    const curToken = localStorage.getItem("agecare_token") || token;
    if (curToken) {
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: {
            Authorization: "Bearer " + curToken,
            "X-Session-Token": curToken,
          },
        });
      } catch (e) {
        // ignore network error
      }
    }
    localStorage.removeItem("agecare_session");
    localStorage.removeItem("agecare_token");
    localStorage.removeItem("agecare_role");
    localStorage.removeItem("agecare_name");
    localStorage.removeItem("agecare_username");
    localStorage.removeItem("agecare_resident_id");
    redirect("/login");
  };

  // Populate signed-in user name and nav links on DOM ready
  document.addEventListener("DOMContentLoaded", function () {
    const nameEls = document.querySelectorAll("[data-auth-name]");
    nameEls.forEach(function (el) {
      el.textContent = fullName || username || "Signed-in user";
    });
    const roleEls = document.querySelectorAll("[data-auth-role]");
    roleEls.forEach(function (el) {
      el.textContent = ROLE_LABELS[role] || role;
    });
  });
})();
