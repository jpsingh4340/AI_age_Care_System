// Client-side authentication, strict 4-role guard, and universal ClearScan layout header/hero
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

  // Apply persisted theme (dark default like ClearScan) and font size
  const savedTheme = localStorage.getItem("agecare_theme") || "dark";
  const savedFont = localStorage.getItem("agecare_font") || "md";
  document.documentElement.setAttribute("data-theme", savedTheme);
  document.documentElement.setAttribute("data-font", savedFont);

  window.toggleTheme = function () {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("agecare_theme", next);
    const btn = document.getElementById("csThemeBtn");
    if (btn) btn.textContent = next === "dark" ? "🌙" : "☀️";
  };

  window.cycleFontSize = function () {
    const order = ["md", "lg", "xl"];
    const cur = document.documentElement.getAttribute("data-font") || "md";
    const next = order[(order.indexOf(cur) + 1) % order.length];
    document.documentElement.setAttribute("data-font", next);
    localStorage.setItem("agecare_font", next);
    const btn = document.getElementById("csFontBtn");
    if (btn) btn.textContent = "Aa " + (next === "md" ? "▾" : next.toUpperCase());
  };

  const token = localStorage.getItem("agecare_token") || "";
  const role = (localStorage.getItem("agecare_role") || "").toLowerCase();
  const fullName = localStorage.getItem("agecare_name") || "";
  const username = localStorage.getItem("agecare_username") || "";
  const path = window.location.pathname.toLowerCase();

  function redirect(url) {
    window.location.replace(url);
  }

  // Enforce role access on protected routes
  for (const [routePrefix, allowedRoles] of Object.entries(ALLOWED_ROLES_BY_PATH)) {
    if (path === routePrefix || path.startsWith(routePrefix + "/")) {
      if (!token || !role) {
        redirect("/login?next=" + encodeURIComponent(path));
        return;
      }
      if (!allowedRoles.includes(role)) {
        redirect(HOME_BY_ROLE[role] || "/login");
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
      } catch (e) {}
    }
    localStorage.removeItem("agecare_session");
    localStorage.removeItem("agecare_token");
    localStorage.removeItem("agecare_role");
    localStorage.removeItem("agecare_name");
    localStorage.removeItem("agecare_username");
    localStorage.removeItem("agecare_resident_id");
    redirect("/login");
  };

  function buildNavLinks() {
    const links = [
      { href: "/carer", label: "Carer" },
      { href: "/nurse", label: "Nurse" },
      { href: "/manager", label: "Manager" },
      { href: "/family", label: "Family" },
    ];
    if (role === "nurse") {
      links.push(
        { href: "/guidance", label: "Guidance AI" },
        { href: "/ocr", label: "Report OCR" },
        { href: "/vision", label: "Room Check" },
        { href: "/ask", label: "Ask AI" }
      );
    } else if (role === "carer") {
      links.push({ href: "/ask", label: "Ask AI" });
    }
    return links
      .map(function (l) {
        const current = path === l.href ? ' aria-current="page"' : "";
        return '<a href="' + l.href + '"' + current + ">" + l.label + "</a>";
      })
      .join("");
  }

  // Upgrade every page's topbar to the unified ClearScan header
  document.addEventListener("DOMContentLoaded", function () {
    const curTheme = document.documentElement.getAttribute("data-theme") || "dark";
    const curFont = document.documentElement.getAttribute("data-font") || "md";
    const homeHref = HOME_BY_ROLE[role] || "/login";

    let header = document.querySelector("header.topbar, header.top, header");
    if (!header) {
      header = document.createElement("header");
      document.body.prepend(header);
    }
    header.className = "topbar";
    header.innerHTML = `
      <div class="topbar-inner">
        <a class="brand" href="/welcome">
          <div>
            <span class="brand-title">AgeCare</span>
            <span class="brand-sub">Kōwhai Gardens · 4-Role Intelligence</span>
          </div>
        </a>
        <nav class="role-nav" aria-label="Role and tool navigation">
          ${buildNavLinks()}
        </nav>
        <div class="user-chip">
          <button type="button" class="ctrl-btn" id="csFontBtn" onclick="cycleFontSize()" title="Text size">Aa ${curFont === "md" ? "▾" : curFont.toUpperCase()}</button>
          <button type="button" class="ctrl-btn" id="csThemeBtn" onclick="toggleTheme()" title="Toggle dark/light theme">${curTheme === "dark" ? "🌙" : "☀️"}</button>
          ${
            token
              ? `<span class="user-pill"><strong data-auth-name>${fullName || username}</strong> · ${ROLE_LABELS[role] || role}</span>
                 <button type="button" class="ctrl-btn" onclick="logout()">Sign Out</button>
                 <a class="ctrl-btn" href="${homeHref}" style="border-color:var(--accent); color:var(--accent-ink)">My Portal →</a>`
              : `<a class="ctrl-btn" href="/login">Log In</a>
                 <a class="ctrl-btn" href="/login#register">Sign Up</a>
                 <a class="ctrl-btn" href="/login" style="border-color:var(--accent); color:var(--accent-ink)">Open Portal →</a>`
          }
        </div>
      </div>
    `;

    // Populate any other [data-auth-name] / [data-auth-role] placeholders
    document.querySelectorAll("[data-auth-name]").forEach(function (el) {
      el.textContent = fullName || username || "Signed-in user";
    });
    document.querySelectorAll("[data-auth-role]").forEach(function (el) {
      el.textContent = ROLE_LABELS[role] || role;
    });
  });
})();
