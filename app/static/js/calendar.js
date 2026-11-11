(function () {
    "use strict";

    function esc(val) {
        if (typeof window.fcEscapeHtml === "function") return window.fcEscapeHtml(val);
        return String(val === null || val === undefined ? "" : val);
    }

    function renderDayPanel(day) {
        const panel = document.getElementById("fc-calendar-day-panel");
        if (!panel || !day) return;

        let html =
            '<div class="d-flex justify-content-between align-items-center pb-2 mb-3 border-bottom" style="border-color: var(--border-color) !important;">' +
            '<div><h2 class="h6 fw-bold mb-0">' + esc(day.date) + "</h2>" +
            '<div class="small" style="color: var(--text-muted);">' + esc(day.total_activity) + " recorded item(s)</div></div>" +
            (day.is_today ? '<span class="badge bg-warning-subtle text-warning-emphasis">Today</span>' : "") +
            "</div>";

        if (!day.total_activity) {
            html += '<div class="small" style="color: var(--text-muted);">No task logs, completions, urge events, or reflections recorded on ' + esc(day.date) + ".</div>";
            panel.innerHTML = html;
            return;
        }

        if (day.progress_entries && day.progress_entries.length) {
            html += '<div class="small fw-bold mb-1">Task Progress Entries (' + day.progress_entries.length + ')</div><ul class="list-group list-group-flush small mb-3">';
            day.progress_entries.forEach(function (e) {
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<a href="/task-items/' + encodeURIComponent(e.task_item_id) + '" class="fw-semibold text-decoration-none">' + esc(e.task_item_name) + "</a> " +
                    '<span style="color: var(--text-muted);">(' + esc(e.centered_task_name) + ")</span>" +
                    '<div class="tabular-nums" style="color: var(--text-muted);">' + esc(e.local_time) + " &middot; " + esc(e.quantity_completed) + " " + esc(e.target_unit) + " &middot; " + esc(e.time_spent_minutes) + " min</div>" +
                    "</li>";
            });
            html += "</ul>";
        }

        const compItems = day.completed_items || [];
        const compCentered = day.completed_centered || [];
        if (compItems.length || compCentered.length) {
            html += '<div class="small fw-bold mb-1">Completed Tasks</div><ul class="list-group list-group-flush small mb-3">';
            compItems.forEach(function (ci) {
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<a href="/task-items/' + encodeURIComponent(ci.id) + '" class="fw-semibold text-decoration-none text-success">' + esc(ci.name) + "</a> " +
                    '<span style="color: var(--text-muted);">(' + esc(ci.parent_name) + " &middot; " + esc(ci.local_time) + ")</span></li>";
            });
            compCentered.forEach(function (cc) {
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<a href="/tasks/' + encodeURIComponent(cc.id) + '" class="fw-semibold text-decoration-none text-success">' + esc(cc.name) + "</a> " +
                    '<span style="color: var(--text-muted);">(Centered &middot; ' + esc(cc.local_time) + ")</span></li>";
            });
            html += "</ul>";
        }

        if (day.events && day.events.length) {
            html += '<div class="small fw-bold mb-1">Behavioural Events (' + day.events.length + ')</div><ul class="list-group list-group-flush small mb-3">';
            day.events.forEach(function (ev) {
                const trig = ev.trigger_category || ev.trigger_text || "";
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<div class="d-flex justify-content-between"><a href="/challenges/' + encodeURIComponent(ev.challenge_id) + '" class="fw-semibold text-decoration-none">' + esc(ev.challenge_name) + '</a><span style="color: var(--text-muted);">' + esc(ev.local_time) + "</span></div>" +
                    '<div><span class="badge bg-secondary-subtle text-secondary-emphasis">' + esc(ev.event_type) + '</span> <span class="fw-semibold">' + esc(ev.outcome) + "</span>" +
                    (trig ? " &middot; " + esc(trig) : "") + "</div></li>";
            });
            html += "</ul>";
        }

        const refs = day.reflections || [];
        const recs = day.daily_records || [];
        const cmts = day.comments || [];
        if (refs.length || recs.length || cmts.length) {
            html += '<div class="small fw-bold mb-1">Reflections &amp; Notes</div><ul class="list-group list-group-flush small mb-0">';
            refs.forEach(function (rf) {
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<a href="/challenges/' + encodeURIComponent(rf.challenge_id) + "/daily?date=" + encodeURIComponent(day.date) + '" class="fw-semibold text-decoration-none">' + esc(rf.challenge_name) + " — " + esc(rf.title || "Reflection") + "</a>" +
                    "<div>" + esc(rf.reflection_text) + "</div></li>";
            });
            recs.forEach(function (rec) {
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<a href="/challenges/' + encodeURIComponent(rec.challenge_id) + "/daily?date=" + encodeURIComponent(day.date) + '" class="fw-semibold text-decoration-none">' + esc(rec.challenge_name) + " (Daily Summary)</a>" +
                    "<div>" + (rec.mood ? "[" + esc(rec.mood) + "] " : "") + esc(rec.reflection) + "</div></li>";
            });
            cmts.forEach(function (cm) {
                html +=
                    '<li class="list-group-item bg-transparent px-0 py-1" style="border-color: var(--border-color); color: var(--text-primary);">' +
                    '<a href="/challenges/' + encodeURIComponent(cm.challenge_id) + "/daily?date=" + encodeURIComponent(day.date) + '" class="fw-semibold text-decoration-none">' + esc(cm.challenge_name) + "</a>" +
                    "<div>" + esc(cm.comment_text) + "</div></li>";
            });
            html += "</ul>";
        }

        panel.innerHTML = html;
    }

    document.addEventListener("DOMContentLoaded", function () {
        const root = document.getElementById("fc-calendar-root");
        if (!root) return;

        document.querySelectorAll(".calendar-day").forEach(function (btn) {
            btn.addEventListener("click", async function () {
                const dateStr = btn.getAttribute("data-date");
                if (!dateStr) return;

                document.querySelectorAll(".calendar-day.active").forEach((el) => el.classList.remove("active"));
                btn.classList.add("active");

                const month = root.getAttribute("data-month") || dateStr.slice(0, 7);
                const moduleFilter = root.getAttribute("data-module") || "all";
                const includeDemo = root.getAttribute("data-include-demo") || "1";

                try {
                    const url =
                        "/calendar/day-details?month=" + encodeURIComponent(month) +
                        "&date=" + encodeURIComponent(dateStr) +
                        "&module=" + encodeURIComponent(moduleFilter) +
                        "&include_demo=" + encodeURIComponent(includeDemo);
                    const resp = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
                    const data = await resp.json();
                    if (data.ok && data.day) {
                        renderDayPanel(data.day);
                        const pageUrl =
                            "/calendar?month=" + encodeURIComponent(data.month || month) +
                            "&date=" + encodeURIComponent(data.selected_date || dateStr) +
                            "&module=" + encodeURIComponent(moduleFilter) +
                            "&include_demo=" + encodeURIComponent(includeDemo);
                        if (window.history && typeof window.history.replaceState === "function") {
                            window.history.replaceState({}, "", pageUrl);
                        }
                    }
                } catch (e) {
                    console.error(e);
                }
            });
        });
    });
})();
