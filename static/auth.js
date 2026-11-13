// Shared by every page: sign-in check, navigation bar, footer, and small helpers.
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
    "/handover": ["carer", "nurse"],
    "/guidance": ["nurse"],
    "/ocr": ["nurse"],
    "/doctor-summary": ["nurse"],
    "/vision": ["nurse"],
    "/ask": ["carer", "nurse"],
    "/manager": ["manager"],
    "/family": ["family"],
    "/": ["nurse"],
  };

  const ROLE_LABELS = {
    nurse: "Registered nurse",
    carer: "Carer",
    manager: "Manager",
    family: "Family",
  };

  const NAV_BY_ROLE = {
    nurse: [
      { href: "/nurse", label: "Dashboard" },
      { href: "/nurse/handover", label: "Handovers" },
      { href: "/nurse/schedule", label: "Schedule" },
      { href: "/guidance", label: "Guidance" },
      { href: "/ocr", label: "Reports" },
      { href: "/doctor-summary", label: "Doctor PDF" },
      { href: "/vision", label: "Camera" },
      { href: "/ask", label: "Ask AI" },
    ],
    carer: [
      { href: "/carer", label: "My shift" },
      { href: "/handover", label: "Handover" },
      { href: "/ask", label: "Ask AI" },
    ],
    manager: [{ href: "/manager", label: "User accounts" }],
    family: [{ href: "/family", label: "Updates" }],
  };

  const PUBLIC_NAV = [
    { href: "/welcome", label: "Home" },
    { href: "/static/privacy.html?v=3", label: "Privacy" },
    { href: "/static/terms.html?v=3", label: "Terms" },
  ];

  const token = localStorage.getItem("agecare_token") || "";
  const role = (localStorage.getItem("agecare_role") || "").toLowerCase();
  const fullName = localStorage.getItem("agecare_name") || "";
  const username = localStorage.getItem("agecare_username") || "";
  const path = window.location.pathname.toLowerCase();
  const isPublicPage = path === "/welcome" || path === "/login" || path.startsWith("/static/");

  function redirect(url) {
    window.location.replace(url);
  }

  // Tabs in the same browser share one sign-in. If someone signs in as another person in
  // another tab, reload here so this tab follows that account instead of failing quietly.
  window.addEventListener("storage", function (e) {
    if (e.key === "agecare_token" && e.newValue !== token) window.location.reload();
  });

  // Check the saved role against the real session on the server.
  if (token && !isPublicPage) {
    fetch("/api/auth/me", { headers: { Authorization: "Bearer " + token, "X-Session-Token": token } })
      .then(function (res) {
        if (res.status === 401) {
          ["agecare_session", "agecare_token", "agecare_role", "agecare_name", "agecare_username", "agecare_resident_id"]
            .forEach(function (k) { localStorage.removeItem(k); });
          redirect("/login?next=" + encodeURIComponent(path));
          return null;
        }
        return res.ok ? res.json() : null;
      })
      .then(function (me) {
        if (!me) return;
        if (me.role !== role || me.username !== username) {
          localStorage.setItem("agecare_role", me.role);
          localStorage.setItem("agecare_name", me.full_name);
          localStorage.setItem("agecare_username", me.username);
          window.location.reload();
        }
      })
      .catch(function () {});
  }

  // Send people to sign in, or to their own home page, when they open a page for another role.
  for (const [routePrefix, allowedRoles] of Object.entries(ALLOWED_ROLES_BY_PATH)) {
    const matches = routePrefix === "/" ? path === "/" : path === routePrefix || path.startsWith(routePrefix + "/");
    if (matches) {
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

  // Fetch with the session headers (Authorization, X-Session-Token, X-Role).
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
    while (host.children.length > 3) host.firstChild.remove(); // keep the corner tidy
    setTimeout(function () {
      item.remove();
    }, 3500);
  };

  // Safe element builder: text always goes in with textContent.
  window.h = function (tag, props, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === false || value == null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(kid));
    }
    return node;
  };
  const h = window.h;

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

  // "Nurse Sarah Johnson (RN)" -> "SJ"
  function initials(name) {
    const words = String(name || "")
      .replace(/\(.*?\)/g, "")
      .split(/\s+/)
      .filter((w) => w && !/^(nurse|carer|dr)$/i.test(w));
    return words.slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
  }

  function todayText() {
    return new Date().toLocaleDateString("en-NZ", { weekday: "long", day: "numeric", month: "long" });
  }

  function buildTopbar(header) {
    const signedIn = Boolean(token && role) && !isPublicPage;
    const links = signedIn ? NAV_BY_ROLE[role] || [] : PUBLIC_NAV;

    const brand = h(
      "a",
      { class: "brand", href: signedIn ? HOME_BY_ROLE[role] || "/welcome" : "/welcome" },
      h("img", { src: "/static/img/favicon.png", alt: "", width: "28", height: "28" }),
      h("span", { class: "brand-name", text: "AgeCare" }),
      h("span", { class: "brand-sub", text: "Care Signal" })
    );

    const toggle = h("button", {
      type: "button",
      class: "btn-nav nav-toggle",
      "aria-expanded": "false",
      "aria-controls": "navPanel",
      text: "Menu",
    });
    toggle.addEventListener("click", function () {
      const open = header.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Close" : "Menu";
    });

    const nav = h(
      "nav",
      { class: "nav-links", "aria-label": "Main" },
      links.map(function (l) {
        const cleanHref = l.href.split("?")[0].toLowerCase();
        return h("a", {
          class: "nav-link",
          href: l.href,
          "data-nav": l.href,
          "aria-current": path === cleanHref || (cleanHref === "/nurse" && path === "/") ? "page" : false,
          text: l.label,
        });
      })
    );

    let user;
    if (signedIn) {
      const name = fullName || username || "Signed in";
      const out = h("button", { type: "button", class: "btn-nav", text: "Sign out" });
      out.addEventListener("click", window.logout);
      user = h(
        "div",
        { class: "nav-user" },
        h("span", { class: "avatar", "aria-hidden": "true", text: initials(name) }),
        h(
          "span",
          { class: "who" },
          h("strong", { "data-auth-name": "", text: name }),
          h("span", { "data-auth-role": "", text: ROLE_LABELS[role] || role })
        ),
        out
      );
    } else if (path !== "/login") {
      user = h(
        "div",
        { class: "nav-user" },
        h("a", { class: "btn-nav", href: "/login?v=2#register", text: "Create account" }),
        h("a", { class: "btn-nav solid", href: "/login?v=2", text: "Sign in" })
      );
    } else {
      user = h(
        "div",
        { class: "nav-user" },
        h("a", { class: "btn-nav", href: "/welcome", text: "Back to Home" })
      );
    }

    header.className = "topbar";
    header.replaceChildren(
      h("div", { class: "topbar-inner" }, brand, toggle, h("div", { class: "nav-panel", id: "navPanel" }, nav, user))
    );
  }

  // Small counts on the navigation bar: work waiting for this person.
  async function updateBadges() {
    if (isPublicPage || !token || (role !== "nurse" && role !== "carer")) return;
    let counts;
    try {
      const res = await window.authFetch("/api/workflow/counts");
      if (!res.ok) return;
      counts = await res.json();
    } catch (e) {
      return;
    }
    const target = role === "nurse" ? "/nurse/handover" : "/handover";
    const link = document.querySelector('[data-nav="' + target + '"]');
    if (!link) return;
    let n, words, urgent = false;
    if (role === "nurse") {
      n = (counts.waiting_handovers || 0) + (counts.unread_messages || 0);
      urgent = (counts.urgent_messages || 0) > 0;
      words = (counts.waiting_handovers || 0) + " handovers waiting, " + (counts.unread_messages || 0) + " unread family messages" +
        (urgent ? ", " + counts.urgent_messages + " urgent" : "");
    } else {
      n = counts.returned_handovers || 0;
      words = n + " handovers sent back to you";
    }
    let badge = link.querySelector(".nav-badge");
    if (!n) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = h("span", { class: "nav-badge" });
      link.append(badge);
    }
    badge.textContent = String(n);
    badge.className = "nav-badge" + (urgent ? " urgent" : "");
    badge.setAttribute("aria-label", words);
    badge.title = words;
  }
  window.updateBadges = updateBadges;

  function buildFooter(footer) {
    footer.className = "foot";
    footer.replaceChildren(
      h(
        "div",
        { class: "foot-grid" },
        h(
          "div",
          { class: "foot-col" },
          h("strong", { class: "foot-title", text: "AgeCare — Care Signal" }),
          h("p", {
            text: "Supporting New Zealand rest-home carers, registered nurses, managers, and families with connected shift handovers, NZEWS priority checks, OCR health report reading, and nurse-approved care guidance.",
          })
        ),
        h(
          "div",
          { class: "foot-col" },
          h("strong", { class: "foot-title", text: "Created By" }),
          h("p", { text: "Jaspreet Singh" }),
          h("p", { text: "Dhruv" }),
          h("p", { text: "Tanveer" })
        ),
        h(
          "div",
          { class: "foot-col" },
          h("strong", { class: "foot-title", text: "Contact Details" }),
          h("p", { text: "Email: support@agecare.co.nz" }),
          h("p", { text: "Phone: +64 9 302 4810" }),
          h("p", { text: "Auckland, New Zealand" })
        ),
        h(
          "div",
          { class: "foot-col" },
          h("strong", { class: "foot-title", text: "Navigation" }),
          h("a", { href: "/welcome", text: "Home" }),
          h("a", { href: "/login", text: "Sign in" }),
          h("a", { href: "/static/privacy.html?v=2", text: "Privacy Policy" }),
          h("a", { href: "/static/terms.html?v=2", text: "Terms of Use" })
        )
      ),
      h(
        "div",
        { class: "foot-inner" },
        h("p", {
          text: "© 2026 AgeCare · Developed by Jaspreet, Dhruv, and Tanveer. All rights reserved.",
        }),
        h(
          "div",
          { class: "foot-links" },
          h("a", { href: "/welcome", text: "Home" }),
          h("a", { href: "/static/privacy.html?v=2", text: "Privacy" }),
          h("a", { href: "/static/terms.html?v=2", text: "Terms" })
        )
      )
    );
  }

  document.addEventListener("DOMContentLoaded", function () {
    let header = document.querySelector("header");
    if (!header) {
      header = document.createElement("header");
      document.body.prepend(header);
    }
    buildTopbar(header);
    updateBadges();
    setInterval(updateBadges, 30000);

    let footer = document.querySelector("footer");
    if (!footer) {
      footer = document.createElement("footer");
      document.body.appendChild(footer);
    }
    buildFooter(footer);

    // Pages can show today's date and the signed-in name in their heading.
    document.querySelectorAll("[data-today]").forEach(function (el) {
      el.textContent = todayText();
    });
    document.querySelectorAll("[data-auth-name]").forEach(function (el) {
      el.textContent = fullName || username || "Signed in";
    });
  });
})();
