(function () {
    "use strict";

    let charts = {};
    let urgeGranularity = "daily";

    function destroyChart(key) {
        if (charts[key]) {
            charts[key].destroy();
            charts[key] = null;
        }
    }

    function esc(val) {
        if (typeof window.fcEscapeHtml === "function") return window.fcEscapeHtml(val);
        return String(val === null || val === undefined ? "" : val);
    }

    function getIsoWeekKey(dateStr) {
        if (!dateStr) return "";
        const d = new Date(dateStr + "T00:00:00Z");
        if (isNaN(d.getTime())) return "";
        const dayNum = d.getUTCDay() || 7;
        d.setUTCDate(d.getUTCDate() + 4 - dayNum);
        const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
        const weekNo = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
        return d.getUTCFullYear() + "-W" + (weekNo < 10 ? "0" + weekNo : "" + weekNo);
    }

    function showDrilldownModal(title, subtitle, bodyHtml) {
        const modalEl = document.getElementById("fc-stats-drilldown-modal");
        if (!modalEl || !window.bootstrap) return;
        const titleEl = document.getElementById("fc-drilldown-title");
        const subEl = document.getElementById("fc-drilldown-subtitle");
        const bodyEl = document.getElementById("fc-drilldown-body");
        if (titleEl) titleEl.textContent = title;
        if (subEl) subEl.textContent = subtitle || "";
        if (bodyEl) bodyEl.innerHTML = bodyHtml;
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    function renderTaskDrilldown(dateStr) {
        const entries = (window.GLOBAL_STATS.tasks && window.GLOBAL_STATS.tasks.drilldown_entries) || [];
        const matched = entries.filter((e) => e.date === dateStr);
        if (!matched.length) {
            showDrilldownModal("Task Logs — " + dateStr, "0 entries", '<p class="small mb-0">No progress entries found for this date.</p>');
            return;
        }
        const rows = matched
            .map(
                (e) =>
                    "<tr>" +
                    '<td class="text-nowrap">' + esc(e.timestamp) + "</td>" +
                    "<td>" + esc(e.centered_task) + "</td>" +
                    '<td><a href="/task-items/' + encodeURIComponent(e.task_item_id) + '" class="text-decoration-none fw-semibold">' + esc(e.task_item) + "</a></td>" +
                    '<td class="tabular-nums">' + esc(e.quantity) + " " + esc(e.unit) + "</td>" +
                    '<td class="tabular-nums">' + esc(e.minutes) + " min</td>" +
                    "<td>" + esc(e.comments) + "</td>" +
                    "</tr>"
            )
            .join("");
        const html =
            '<div class="table-responsive"><table class="table table-sm align-middle small mb-0">' +
            "<thead><tr><th>Time</th><th>Centered Task</th><th>Internal Task</th><th>Quantity</th><th>Duration</th><th>Comments</th></tr></thead>" +
            "<tbody>" + rows + "</tbody></table></div>";
        showDrilldownModal("Task Logs — " + dateStr, matched.length + " entry record(s)", html);
    }

    function renderEventDrilldown(title, matched) {
        if (!matched.length) {
            showDrilldownModal(title, "0 events", '<p class="small mb-0">No matching events in this bucket.</p>');
            return;
        }
        const rows = matched
            .map(
                (e) =>
                    "<tr>" +
                    '<td class="text-nowrap">' + esc(e.timestamp) + "</td>" +
                    '<td><a href="/challenges/' + encodeURIComponent(e.challenge_id) + '" class="text-decoration-none fw-semibold">' + esc(e.challenge_name) + "</a></td>" +
                    '<td><span class="badge bg-secondary-subtle text-secondary-emphasis">' + esc(e.event_type) + "</span></td>" +
                    "<td>" + esc(e.outcome) + "</td>" +
                    "<td>" + esc(e.trigger_category) + (e.trigger_text && e.trigger_text !== e.trigger_category ? " — " + esc(e.trigger_text) : "") + "</td>" +
                    "<td>" + esc(e.comments) + "</td>" +
                    "</tr>"
            )
            .join("");
        const html =
            '<div class="table-responsive"><table class="table table-sm align-middle small mb-0">' +
            "<thead><tr><th>Time</th><th>Challenge</th><th>Type</th><th>Outcome</th><th>Trigger</th><th>Comments</th></tr></thead>" +
            "<tbody>" + rows + "</tbody></table></div>";
        showDrilldownModal(title, matched.length + " event record(s)", html);
    }

    function renderUrgeTrend() {
        const stats = window.GLOBAL_STATS;
        const canvas = document.getElementById("statUrgeTrendChart");
        if (!canvas || !stats) return;
        const colors = window.fcChartColors();

        let src = stats.challenges.daily_series || [];
        let labelKey = "date";
        if (urgeGranularity === "weekly") {
            src = stats.challenges.weekly_series || [];
            labelKey = "week";
        } else if (urgeGranularity === "monthly") {
            src = stats.challenges.monthly_series || [];
            labelKey = "month";
        }
        if (!src.length) return;

        destroyChart("urgeTrend");
        charts.urgeTrend = new Chart(canvas, {
            type: "bar",
            data: {
                labels: src.map((x) => x[labelKey]),
                datasets: [
                    { label: "Thoughts", data: src.map((x) => x.thoughts), backgroundColor: "#6366f1" },
                    { label: "Resisted", data: src.map((x) => x.resisted), backgroundColor: "#10b981" },
                    { label: "Gave In", data: src.map((x) => x.gave_in), backgroundColor: "#f59e0b" },
                    { label: "Actions", data: src.map((x) => x.actions), backgroundColor: "#e11d48" },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: function (_ev, elements) {
                    if (!elements || !elements.length) return;
                    const idx = elements[0].index;
                    const key = src[idx] ? src[idx][labelKey] : "";
                    if (!key) return;
                    const allEvs = (stats.challenges && stats.challenges.drilldown_events) || [];
                    const matched = allEvs.filter(function (e) {
                        if (urgeGranularity === "weekly") return getIsoWeekKey(e.date) === key;
                        if (urgeGranularity === "monthly") return (e.date || "").slice(0, 7) === key;
                        return e.date === key;
                    });
                    renderEventDrilldown("Events — " + key, matched);
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0, color: colors.text }, grid: { color: colors.grid } },
                    x: { ticks: { color: colors.text }, grid: { display: false } },
                },
                plugins: { legend: { labels: { color: colors.text } } },
            },
        });
    }

    function renderAllStatsCharts() {
        const stats = window.GLOBAL_STATS;
        if (!stats) return;
        const colors = window.fcChartColors();

        // 1. Task Time Distribution Doughnut
        const distCanvas = document.getElementById("statTaskDistChart");
        if (distCanvas && stats.tasks.distribution && stats.tasks.distribution.length) {
            destroyChart("taskDist");
            charts.taskDist = new Chart(distCanvas, {
                type: "doughnut",
                data: {
                    labels: stats.tasks.distribution.map((t) => t.name),
                    datasets: [
                        {
                            data: stats.tasks.distribution.map((t) => t.actual_hours > 0 ? t.actual_hours : t.allocated_target),
                            backgroundColor: stats.tasks.distribution.map((t) => t.color || "#4f46e5"),
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: "bottom", labels: { color: colors.text } } },
                },
            });
        }

        // 2. Allocated vs Actual Bar
        const allocCanvas = document.getElementById("statTaskAllocChart");
        if (allocCanvas && stats.tasks.distribution && stats.tasks.distribution.length) {
            destroyChart("taskAlloc");
            charts.taskAlloc = new Chart(allocCanvas, {
                type: "bar",
                data: {
                    labels: stats.tasks.distribution.map((t) => t.name),
                    datasets: [
                        { label: "Allocated Target", data: stats.tasks.distribution.map((t) => t.allocated_target), backgroundColor: "#94a3b8", borderRadius: 5 },
                        { label: "Actual Logged Hours", data: stats.tasks.distribution.map((t) => t.actual_hours), backgroundColor: "#4f46e5", borderRadius: 5 },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, ticks: { color: colors.text }, grid: { color: colors.grid } },
                        x: { ticks: { color: colors.text }, grid: { display: false } },
                    },
                    plugins: { legend: { labels: { color: colors.text } } },
                },
            });
        }

        // 3. Daily Task Hours (Interactive Drilldown)
        const dailyTaskCanvas = document.getElementById("statTaskDailyChart");
        if (dailyTaskCanvas && stats.tasks.daily_series && stats.tasks.daily_series.length) {
            destroyChart("taskDaily");
            charts.taskDaily = new Chart(dailyTaskCanvas, {
                type: "line",
                data: {
                    labels: stats.tasks.daily_series.map((d) => d.date),
                    datasets: [
                        {
                            label: "Hours Logged",
                            data: stats.tasks.daily_series.map((d) => d.hours),
                            borderColor: "#0ea5e9",
                            backgroundColor: "rgba(14, 165, 233, 0.14)",
                            fill: true,
                            tension: 0.3,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: function (_ev, elements) {
                        if (!elements || !elements.length) return;
                        const idx = elements[0].index;
                        const row = stats.tasks.daily_series[idx];
                        if (row && row.date) renderTaskDrilldown(row.date);
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { color: colors.text }, grid: { color: colors.grid } },
                        x: { ticks: { color: colors.text }, grid: { display: false } },
                    },
                    plugins: { legend: { labels: { color: colors.text } } },
                },
            });
        }

        // 4. Completion Trend
        const compCanvas = document.getElementById("statTaskCompChart");
        if (compCanvas && stats.tasks.completion_trend && stats.tasks.completion_trend.length) {
            destroyChart("taskComp");
            charts.taskComp = new Chart(compCanvas, {
                type: "bar",
                data: {
                    labels: stats.tasks.completion_trend.map((c) => c.date),
                    datasets: [
                        { label: "Tasks Completed", data: stats.tasks.completion_trend.map((c) => c.completed), backgroundColor: "#10b981", borderRadius: 5 },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0, color: colors.text }, grid: { color: colors.grid } },
                        x: { ticks: { color: colors.text }, grid: { display: false } },
                    },
                    plugins: { legend: { labels: { color: colors.text } } },
                },
            });
        }

        // 5. Urge Trend (Daily/Weekly/Monthly)
        renderUrgeTrend();

        // 6. Hourly 24h Distribution
        const hrCanvas = document.getElementById("statUrgeHourlyChart");
        if (hrCanvas && stats.challenges.hourly_distribution) {
            destroyChart("urgeHourly");
            charts.urgeHourly = new Chart(hrCanvas, {
                type: "line",
                data: {
                    labels: stats.challenges.hourly_distribution.map((h) => h.hour),
                    datasets: [
                        { label: "Thoughts", data: stats.challenges.hourly_distribution.map((h) => h.thoughts), borderColor: "#6366f1", tension: 0.3 },
                        { label: "Urges", data: stats.challenges.hourly_distribution.map((h) => h.urges), borderColor: "#f59e0b", tension: 0.3 },
                        { label: "Actions", data: stats.challenges.hourly_distribution.map((h) => h.actions), borderColor: "#e11d48", tension: 0.3 },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0, color: colors.text }, grid: { color: colors.grid } },
                        x: { ticks: { color: colors.text, maxTicksLimit: 12 }, grid: { display: false } },
                    },
                    plugins: { legend: { labels: { color: colors.text } } },
                },
            });
        }

        // 7. Top Triggers Horizontal Bar (Interactive Drilldown)
        const trigCanvas = document.getElementById("statTriggerChart");
        if (trigCanvas && stats.challenges.top_triggers && stats.challenges.top_triggers.length) {
            destroyChart("triggers");
            charts.triggers = new Chart(trigCanvas, {
                type: "bar",
                data: {
                    labels: stats.challenges.top_triggers.map((t) => t.trigger),
                    datasets: [
                        { label: "Occurrences", data: stats.challenges.top_triggers.map((t) => t.count), backgroundColor: "#0d9488", borderRadius: 5 },
                    ],
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: function (_ev, elements) {
                        if (!elements || !elements.length) return;
                        const idx = elements[0].index;
                        const item = stats.challenges.top_triggers[idx];
                        if (!item) return;
                        const allEvs = (stats.challenges && stats.challenges.drilldown_events) || [];
                        const matched = allEvs.filter((e) => e.trigger_category === item.trigger);
                        renderEventDrilldown("Trigger Events — " + item.trigger, matched);
                    },
                    scales: {
                        x: { beginAtZero: true, ticks: { precision: 0, color: colors.text }, grid: { color: colors.grid } },
                        y: { ticks: { color: colors.text }, grid: { display: false } },
                    },
                    plugins: { legend: { display: false } },
                },
            });
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".stat-trend-granularity").forEach(function (btn) {
            btn.addEventListener("click", function () {
                document.querySelectorAll(".stat-trend-granularity").forEach((b) => b.classList.remove("active"));
                btn.classList.add("active");
                urgeGranularity = btn.getAttribute("data-gran") || "daily";
                renderUrgeTrend();
            });
        });
        renderAllStatsCharts();
    });
    window.addEventListener("fc:themechange", renderAllStatsCharts);
})();
