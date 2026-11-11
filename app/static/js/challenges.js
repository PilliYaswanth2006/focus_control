(function () {
    "use strict";

    function initChallengeMetaBuilder() {
        const addBtn = document.getElementById("add-ch-meta-row");
        const container = document.getElementById("ch-meta-container");
        if (!addBtn || !container) return;
        addBtn.addEventListener("click", function () {
            const row = document.createElement("div");
            row.className = "row g-2 ch-meta-row";
            row.innerHTML =
                '<div class="col-5"><input type="text" name="meta_key" class="form-control form-control-sm" placeholder="Key"></div>' +
                '<div class="col-6"><input type="text" name="meta_value" class="form-control form-control-sm" placeholder="Value"></div>' +
                '<div class="col-1"><button type="button" class="btn btn-sm btn-outline-danger w-100 remove-ch-meta">&times;</button></div>';
            container.appendChild(row);
        });
        container.addEventListener("click", function (ev) {
            if (ev.target.classList.contains("remove-ch-meta")) {
                ev.target.closest(".ch-meta-row").remove();
            }
        });
    }

    function initChallengeFormBehavior() {
        const startInput = document.getElementById("ch-start-date");
        const endInput = document.getElementById("ch-end-date");
        const durInput = document.getElementById("ch-duration-days");
        const durHint = document.getElementById("ch-duration-hint");

        if (startInput && endInput && durInput) {
            if (!durInput.value) {
                durInput.dataset.autoComputed = "1";
            }
            durInput.addEventListener("input", function () {
                durInput.dataset.autoComputed = durInput.value ? "0" : "1";
            });
            function recalcDuration() {
                if (!startInput.value || !endInput.value) return;
                const sMs = Date.parse(startInput.value + "T00:00:00Z");
                const eMs = Date.parse(endInput.value + "T00:00:00Z");
                if (isNaN(sMs) || isNaN(eMs) || eMs < sMs) return;
                const days = Math.round((eMs - sMs) / 86400000) + 1;
                if (durHint) durHint.textContent = "Computed from dates: " + days + " day(s).";
                if (durInput.dataset.autoComputed === "1" || !durInput.value) {
                    durInput.value = String(days);
                    durInput.dataset.autoComputed = "1";
                }
            }
            startInput.addEventListener("change", recalcDuration);
            endInput.addEventListener("change", recalcDuration);
        }

        const bgPreset = document.getElementById("ch-bg-preset");
        const bgFile = document.getElementById("ch-bg-file");
        const bgPreview = document.getElementById("ch-bg-preview");
        const bgLabel = document.getElementById("ch-bg-preview-label");
        if (bgPreview && (bgPreset || bgFile)) {
            function setPreview(url, emptyText) {
                if (url) {
                    bgPreview.style.backgroundImage = "url('" + url + "')";
                    if (bgLabel) bgLabel.textContent = "";
                } else {
                    bgPreview.style.backgroundImage = "";
                    if (bgLabel) bgLabel.textContent = emptyText || "No background selected";
                }
            }
            if (bgPreset) {
                bgPreset.addEventListener("change", function () {
                    if (bgFile && bgFile.files && bgFile.files.length) return;
                    const opt = bgPreset.options[bgPreset.selectedIndex];
                    setPreview(opt ? opt.getAttribute("data-preview-url") : "");
                });
            }
            if (bgFile) {
                bgFile.addEventListener("change", function () {
                    if (bgFile.files && bgFile.files[0]) {
                        setPreview(URL.createObjectURL(bgFile.files[0]));
                    } else if (bgPreset) {
                        const opt = bgPreset.options[bgPreset.selectedIndex];
                        setPreview(opt ? opt.getAttribute("data-preview-url") : "");
                    }
                });
            }
        }
    }

    function initEventModal() {
        const modalEl = document.getElementById("fc-event-modal");
        if (!modalEl) return;
        const modal = new bootstrap.Modal(modalEl);
        const form = document.getElementById("fc-event-form");
        const titleEl = document.getElementById("fc-event-modal-title");
        const typeSel = document.getElementById("fc-event-type");
        const outcomeWrap = document.getElementById("fc-outcome-wrap");
        const outcomeSel = document.getElementById("fc-event-outcome");
        const relUrgeWrap = document.getElementById("fc-related-urge-wrap");
        const relUrgeSel = document.getElementById("fc-related-urge");
        const tsInput = document.getElementById("fc-event-ts");
        const durInput = document.getElementById("fc-event-dur");
        const trigCatSel = document.getElementById("fc-event-trigger-cat");
        const trigInput = document.getElementById("fc-event-trigger");
        const ctxInput = document.getElementById("fc-event-context");
        const tagsInput = document.getElementById("fc-event-tags");
        const cmtInput = document.getElementById("fc-event-comments");

        function syncTypeVisibility() {
            const val = typeSel.value;
            if (val === "URGE") {
                outcomeWrap.classList.remove("d-none");
                relUrgeWrap.classList.add("d-none");
            } else if (val === "ACTION") {
                outcomeWrap.classList.add("d-none");
                relUrgeWrap.classList.remove("d-none");
            } else {
                outcomeWrap.classList.add("d-none");
                relUrgeWrap.classList.add("d-none");
            }
        }
        typeSel.addEventListener("change", syncTypeVisibility);

        document.addEventListener("click", function (ev) {
            const addBtn = ev.target.closest(".fc-open-event-btn");
            if (addBtn) {
                form.action = addBtn.getAttribute("data-action");
                titleEl.textContent = "Record Behavioural Event";
                typeSel.value = addBtn.getAttribute("data-type") || "URGE";
                outcomeSel.value = addBtn.getAttribute("data-outcome") || "Resisted";
                tsInput.value = addBtn.getAttribute("data-ts") || "";
                durInput.value = "0";
                if (trigCatSel) trigCatSel.value = "";
                trigInput.value = "";
                ctxInput.value = "";
                tagsInput.value = "";
                cmtInput.value = "";
                if (relUrgeSel) relUrgeSel.value = "";
                syncTypeVisibility();
                modal.show();
                return;
            }
            const editBtn = ev.target.closest(".fc-edit-event-btn");
            if (editBtn) {
                form.action = editBtn.getAttribute("data-action");
                titleEl.textContent = "Edit Event Record";
                typeSel.value = editBtn.getAttribute("data-type") || "URGE";
                outcomeSel.value = editBtn.getAttribute("data-outcome") || "Resisted";
                tsInput.value = editBtn.getAttribute("data-ts") || "";
                durInput.value = editBtn.getAttribute("data-dur") || "0";
                if (trigCatSel) trigCatSel.value = editBtn.getAttribute("data-trigger-category") || "";
                trigInput.value = editBtn.getAttribute("data-trigger") || "";
                ctxInput.value = editBtn.getAttribute("data-context") || "";
                tagsInput.value = editBtn.getAttribute("data-tags") || "";
                cmtInput.value = editBtn.getAttribute("data-comments") || "";
                if (relUrgeSel) relUrgeSel.value = editBtn.getAttribute("data-related-urge") || "";
                syncTypeVisibility();
                modal.show();
            }
        });
    }

    function initCommentEditToggles() {
        document.addEventListener("click", function (ev) {
            const btn = ev.target.closest(".fc-toggle-edit-comment, .fc-toggle-edit-reflection");
            if (!btn) return;
            const targetId = btn.getAttribute("data-target");
            const form = document.getElementById(targetId);
            if (form) form.classList.toggle("d-none");
        });
    }

    let dailyChart = null;
    let hourlyChart = null;

    function renderChallengeCharts() {
        const data = window.CHALLENGE_CHART_DATA;
        if (!data) return;
        const colors = window.fcChartColors();

        const dailyCanvas = document.getElementById("chDailyChart");
        if (dailyCanvas && data.daily_series && data.daily_series.length) {
            if (dailyChart) dailyChart.destroy();
            dailyChart = new Chart(dailyCanvas, {
                type: "bar",
                data: {
                    labels: data.daily_series.map((d) => d.date),
                    datasets: [
                        { label: "Thoughts", data: data.daily_series.map((d) => d.thoughts), backgroundColor: "#6366f1" },
                        { label: "Resisted Urges", data: data.daily_series.map((d) => d.resisted), backgroundColor: "#10b981" },
                        { label: "Gave-In Urges", data: data.daily_series.map((d) => d.gave_in), backgroundColor: "#f59e0b" },
                        { label: "Actions", data: data.daily_series.map((d) => d.actions), backgroundColor: "#e11d48" },
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

        const hourlyCanvas = document.getElementById("chHourlyChart");
        if (hourlyCanvas && data.hourly_distribution) {
            if (hourlyChart) hourlyChart.destroy();
            hourlyChart = new Chart(hourlyCanvas, {
                type: "line",
                data: {
                    labels: data.hourly_distribution.map((h) => h.hour),
                    datasets: [
                        { label: "Thoughts", data: data.hourly_distribution.map((h) => h.thoughts), borderColor: "#6366f1", tension: 0.3 },
                        { label: "Urges", data: data.hourly_distribution.map((h) => h.urges), borderColor: "#f59e0b", tension: 0.3 },
                        { label: "Actions", data: data.hourly_distribution.map((h) => h.actions), borderColor: "#e11d48", tension: 0.3 },
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
    }

    document.addEventListener("DOMContentLoaded", function () {
        initChallengeMetaBuilder();
        initChallengeFormBehavior();
        initEventModal();
        initCommentEditToggles();
        renderChallengeCharts();
    });
    window.addEventListener("fc:themechange", renderChallengeCharts);
})();
