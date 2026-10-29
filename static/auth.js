// Client-side authentication, role navigation, and layout helpers
(function () {
  const HOME_BY_ROLE = {
    nurse: "/nurse",
    carer: "/carer",
    manager: "/manager",
    family: "/family",
  };

  const ALLOWED_ROLES_BY_PATH = {
    "/nurse": ["nurse"],
    "/carer": ["carer", "nurse"],
    "/guidance": ["nurse"],
    "/ocr": ["nurse"],
    "/vision": ["nurse"],
    "/ask": ["carer", "nurse"],
    "/manager": ["manager"],
    "/family": ["family"],
  };

  const ROLE_LABELS = {
    nurse: "Registered Nurse",
    carer: "Care Assistant",
    manager: "Manager / Admin",
    family: "Whānau / Family",
  };

  const token = localStorage.getItem("agecare_token") || "";
  const role = (localStorage.getItem("agecare_role") || "").toLowerCase();
  const fullName = localStorage.getItem("agecare_name") || "";
  const username = localStorage.getItem("agecare_username") || "";
  const path = window.location.pathname.toLowerCase();

  function redirect(url) {
    window.location.replace(url);
  }

  // Enforce role guard on role-restricted pages
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

  // Global authenticated fetch helper (preserves Authorization, X-Session-Token, and X-Role headers)
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

  // Toast notification helper
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

  // Safe element builder helper
  window.h = function (tag, props, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === false || value == null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(kid));
    }
    return node;
  };

  // Logout helper
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
    if (path === "/welcome" || path === "/login") {
      return "";
    }
    if (!token || !role) {
      return "";
    }
    const links = [];
    if (role === "nurse") {
      links.push(
        { href: "/nurse", label: "Nurse Dashboard" },
        { href: "/guidance", label: "Guidance" },
        { href: "/ocr", label: "Health Report OCR" },
        { href: "/vision", label: "Face & Room Check" },
        { href: "/ask", label: "Ask AI" }
      );
    } else if (role === "carer") {
      links.push(
        { href: "/carer", label: "Carer Sheet" },
        { href: "/ask", label: "Ask AI" }
      );
    } else if (role === "manager") {
      links.push(
        { href: "/manager", label: "Manager & Accounts" }
      );
    } else if (role === "family") {
      links.push(
        { href: "/family", label: "Family Portal" }
      );
    }

    if (!links.length) return "";
    const items = links.map(function (l) {
      const current = path === l.href ? ' aria-current="page"' : "";
      return '<a class="nav-link" href="' + l.href + '"' + current + ">" + l.label + "</a>";
    }).join("");

    return '<nav class="topbar-nav" aria-label="Main Navigation">' + items + '</nav>';
  }

  const FOOTER_HTML = `
    <div class="foot-inner">
      <div>
        <strong>Age-Care Intelligence System</strong> · Student Prototype (Studio 5). Fictional resident data only. Local AI via Ollama. Photos are not saved. Not a medical device.
      </div>
      <div class="foot-links">
        <a href="/welcome">Overview</a>
        <a href="/static/privacy.html">Privacy</a>
        <a href="/static/terms.html">Terms</a>
      </div>
    </div>
  `;

  document.addEventListener("DOMContentLoaded", function () {
    const isPublicPage = path === "/welcome" || path === "/login";

    // Topbar injection
    let header = document.querySelector("header.topbar, header");
    if (!header) {
      header = document.createElement("header");
      document.body.prepend(header);
    }
    header.className = "topbar";
    header.innerHTML = `
      <div class="topbar-inner">
        <a class="brand" href="/welcome">
          <span>AgeCare</span>
          <span class="brand-badge">Clinical</span>
        </a>
        ${buildNavLinks()}
        <div class="topbar-user">
          ${
            token && !isPublicPage
              ? `<span class="user-tag">
                   <strong data-auth-name>${fullName || username}</strong>
                   <span class="role-badge" data-auth-role>${ROLE_LABELS[role] || role}</span>
                 </span>
                 <button type="button" class="btn btn-secondary btn-sm" onclick="logout()">Sign out</button>`
              : `<a href="/login" class="btn btn-primary btn-sm">Sign in</a>`
          }
        </div>
      </div>
    `;

    // Footer injection
    let footer = document.querySelector("footer.foot, footer");
    if (!footer) {
      footer = document.createElement("footer");
      document.body.appendChild(footer);
    }
    footer.className = "foot";
    footer.innerHTML = FOOTER_HTML;

    // Replace data-auth placeholders
    document.querySelectorAll("[data-auth-name]").forEach(function (el) {
      el.textContent = fullName || username || "Signed-in User";
    });
    document.querySelectorAll("[data-auth-role]").forEach(function (el) {
      el.textContent = ROLE_LABELS[role] || role;
    });
  });
})();
