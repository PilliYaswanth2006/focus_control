/* Focus & Control Shared UI Utilities */
(function () {
    "use strict";

    function initIcons() {
        if (window.lucide && typeof window.lucide.createIcons === "function") {
            window.lucide.createIcons();
        }
    }

    window.fcToast = function (message, category) {
        const container = document.getElementById("fc-toast-container");
        if (!container) return;
        const typeMap = {
            success: "text-bg-success",
            danger: "text-bg-danger",
            warning: "text-bg-warning",
            info: "text-bg-primary",
        };
        const cls = typeMap[category] || "text-bg-dark";
        const toastEl = document.createElement("div");
        toastEl.className = "toast align-items-center border-0 " + cls;
        toastEl.setAttribute("role", "alert");
        toastEl.innerHTML =
            '<div class="d-flex">' +
            '<div class="toast-body"></div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
            "</div>";
        toastEl.querySelector(".toast-body").textContent = message;
        container.appendChild(toastEl);
        const bsToast = new bootstrap.Toast(toastEl, { delay: 3800 });
        bsToast.show();
        toastEl.addEventListener("hidden.bs.toast", function () {
            toastEl.remove();
        });
    };

    window.fcEscapeHtml = function (str) {
        if (str === null || str === undefined) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    };

    function applyResolvedTheme() {
        const root = document.documentElement;
        const pref = root.getAttribute("data-theme-pref");
        if (pref === "system") {
            const isDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
            root.setAttribute("data-theme", isDark ? "dark" : "light");
        }
    }

    function initThemeToggle() {
        applyResolvedTheme();
        if (window.matchMedia) {
            const mq = window.matchMedia("(prefers-color-scheme: dark)");
            if (typeof mq.addEventListener === "function") {
                mq.addEventListener("change", function () {
                    if (document.documentElement.getAttribute("data-theme-pref") === "system") {
                        applyResolvedTheme();
                        window.dispatchEvent(
                            new CustomEvent("fc:themechange", {
                                detail: { theme: document.documentElement.getAttribute("data-theme") },
                            })
                        );
                    }
                });
            }
        }

        const btn = document.getElementById("fc-theme-toggle");
        if (!btn) return;
        btn.addEventListener("click", async function () {
            try {
                const currentResolved = document.documentElement.getAttribute("data-theme") || "light";
                const nextTheme = currentResolved === "dark" ? "light" : "dark";
                const resp = await fetch("/settings/toggle-theme", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: JSON.stringify({ theme: nextTheme }),
                });
                const data = await resp.json();
                if (data.ok) {
                    document.documentElement.setAttribute("data-theme-pref", data.theme);
                    if (data.theme === "system") {
                        applyResolvedTheme();
                    } else {
                        document.documentElement.setAttribute("data-theme", data.theme);
                    }
                    window.dispatchEvent(new CustomEvent("fc:themechange", { detail: { theme: data.theme } }));
                    window.fcToast("Switched to " + data.theme + " theme.", "info");
                }
            } catch (e) {
                console.error(e);
            }
        });
    }

    function initSecretToggles() {
        document.addEventListener("click", function (ev) {
            const btn = ev.target.closest(".fc-toggle-secret");
            if (!btn) return;
            const targetId = btn.getAttribute("data-target");
            const input = targetId
                ? document.getElementById(targetId)
                : btn.closest(".input-group") && btn.closest(".input-group").querySelector("input");
            if (!input) return;

            const isMasked = input.type === "password";
            input.type = isMasked ? "text" : "password";
            btn.setAttribute("aria-label", isMasked ? "Hide value" : "Show value");
            const label = btn.getAttribute("data-label-show") || "Show";
            const hideLabel = btn.getAttribute("data-label-hide") || "Hide";
            btn.textContent = isMasked ? hideLabel : label;
        });
    }

    function initSidebarDrawer() {
        const sidebar = document.getElementById("app-sidebar");
        const backdrop = document.getElementById("sidebar-backdrop");
        const toggleBtn = document.getElementById("sidebar-mobile-toggle");
        if (!sidebar || !toggleBtn || !backdrop) return;

        function closeDrawer() {
            sidebar.classList.remove("open");
            backdrop.classList.remove("show");
        }
        toggleBtn.addEventListener("click", function () {
            sidebar.classList.toggle("open");
            backdrop.classList.toggle("show");
        });
        backdrop.addEventListener("click", closeDrawer);
    }

    function initConfirmationDialogs() {
        const modalEl = document.getElementById("fc-confirm-modal");
        if (!modalEl) return;
        const modal = new bootstrap.Modal(modalEl);
        const titleEl = document.getElementById("fc-confirm-title");
        const msgEl = document.getElementById("fc-confirm-message");
        const confirmBtn = document.getElementById("fc-confirm-submit");
        const extraHiddenContainer = document.getElementById("fc-confirm-extra");

        let pendingForm = null;
        let pendingExtraName = null;
        let pendingExtraVal = null;

        document.addEventListener("click", function (ev) {
            const trigger = ev.target.closest("[data-confirm-message]");
            if (!trigger) return;
            const form = trigger.closest("form");
            if (!form) return;

            ev.preventDefault();
            pendingForm = form;
            pendingExtraName = trigger.getAttribute("data-confirm-input-name");
            pendingExtraVal = trigger.getAttribute("data-confirm-input-value");
            titleEl.textContent = trigger.getAttribute("data-confirm-title") || "Confirm Action";
            msgEl.textContent = trigger.getAttribute("data-confirm-message");
            confirmBtn.textContent = trigger.getAttribute("data-confirm-btn") || "Confirm";
            confirmBtn.className = "btn " + (trigger.getAttribute("data-confirm-class") || "btn-danger");
            modal.show();
        });

        confirmBtn.addEventListener("click", function () {
            if (!pendingForm) return;
            if (extraHiddenContainer) extraHiddenContainer.innerHTML = "";
            if (pendingExtraName) {
                const inp = document.createElement("input");
                inp.type = "hidden";
                inp.name = pendingExtraName;
                inp.value = pendingExtraVal || "1";
                pendingForm.appendChild(inp);
            }
            modal.hide();
            pendingForm.submit();
            pendingForm = null;
        });
    }

    function initFormValidation() {
        document.querySelectorAll("form.needs-validation").forEach(function (form) {
            form.addEventListener(
                "submit",
                function (event) {
                    if (!form.checkValidity()) {
                        event.preventDefault();
                        event.stopPropagation();
                    }
                    form.classList.add("was-validated");
                },
                false
            );
        });
    }

    function initLiveTimers() {
        document.querySelectorAll("[data-timer-start]").forEach(function (el) {
            const startIso = el.getAttribute("data-timer-start");
            if (!startIso) return;
            const startMs = Date.parse(startIso);
            if (isNaN(startMs)) return;

            function tick() {
                const diffSecs = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
                const hrs = Math.floor(diffSecs / 3600);
                const mins = Math.floor((diffSecs % 3600) / 60);
                const secs = diffSecs % 60;
                const pad = function (n) { return n < 10 ? "0" + n : "" + n; };
                el.textContent = (hrs > 0 ? pad(hrs) + ":" : "") + pad(mins) + ":" + pad(secs);
            }
            tick();
            setInterval(tick, 1000);
        });
    }

    window.fcChartColors = function () {
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        return {
            text: isDark ? "#cbd5e1" : "#475569",
            grid: isDark ? "rgba(148, 163, 184, 0.14)" : "rgba(15, 23, 42, 0.08)",
            surface: isDark ? "#131a26" : "#ffffff",
        };
    };

    document.addEventListener("DOMContentLoaded", function () {
        initIcons();
        initThemeToggle();
        initSecretToggles();
        initSidebarDrawer();
        initConfirmationDialogs();
        initFormValidation();
        initLiveTimers();
    });
})();
