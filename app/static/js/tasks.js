(function () {
    "use strict";

    function initTaskFormBehavior() {
        const modeSel = document.getElementById("ct-alloc-mode");
        const targetWrap = document.getElementById("ct-manual-target-wrap");
        if (modeSel && targetWrap) {
            function syncAllocMode() {
                const isManual = modeSel.value === "manual";
                targetWrap.style.opacity = isManual ? "1" : "0.65";
            }
            modeSel.addEventListener("change", syncAllocMode);
            syncAllocMode();
        }

        const addMetaBtn = document.getElementById("add-meta-row");
        const metaContainer = document.getElementById("meta-kv-container");
        if (addMetaBtn && metaContainer) {
            addMetaBtn.addEventListener("click", function () {
                const row = document.createElement("div");
                row.className = "row g-2 meta-kv-row";
                row.innerHTML =
                    '<div class="col-5"><input type="text" name="meta_key" class="form-control form-control-sm" placeholder="Key"></div>' +
                    '<div class="col-6"><input type="text" name="meta_value" class="form-control form-control-sm" placeholder="Value"></div>' +
                    '<div class="col-1"><button type="button" class="btn btn-sm btn-outline-danger w-100 remove-meta-row">&times;</button></div>';
                metaContainer.appendChild(row);
            });
            metaContainer.addEventListener("click", function (ev) {
                if (ev.target.classList.contains("remove-meta-row")) {
                    ev.target.closest(".meta-kv-row").remove();
                }
            });
        }

        const bgPreset = document.getElementById("ct-bg-preset");
        const bgFile = document.getElementById("ct-bg-file");
        const bgPreview = document.getElementById("ct-bg-preview");
        const bgLabel = document.getElementById("ct-bg-preview-label");
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
                        const objUrl = URL.createObjectURL(bgFile.files[0]);
                        setPreview(objUrl);
                    } else if (bgPreset) {
                        const opt = bgPreset.options[bgPreset.selectedIndex];
                        setPreview(opt ? opt.getAttribute("data-preview-url") : "");
                    }
                });
            }
        }
    }

    function initAddItemTypeSwitch() {
        const rStd = document.getElementById("add-type-std");
        const rLink = document.getElementById("add-type-link");
        const stdWrap = document.getElementById("std-fields-wrap");
        const linkWrap = document.getElementById("link-fields-wrap");
        const nameInput = document.getElementById("add-item-name");
        const linkSelect = document.getElementById("add-item-link-select");
        if (!rStd || !rLink || !stdWrap || !linkWrap) return;

        function sync() {
            if (rLink.checked) {
                stdWrap.classList.add("d-none");
                linkWrap.classList.remove("d-none");
                if (nameInput) nameInput.required = false;
                if (linkSelect) linkSelect.required = true;
            } else {
                stdWrap.classList.remove("d-none");
                linkWrap.classList.add("d-none");
                if (nameInput) nameInput.required = true;
                if (linkSelect) linkSelect.required = false;
            }
        }
        rStd.addEventListener("change", sync);
        rLink.addEventListener("change", sync);
        sync();
    }

    function initWeightLiveCalculators() {
        const rootInputs = document.querySelectorAll(".root-weight-input");
        const rootTotalEl = document.getElementById("root-weight-total");
        if (rootInputs.length && rootTotalEl) {
            function recalcRoot() {
                let sum = 0;
                rootInputs.forEach(function (inp) {
                    const w = parseFloat(inp.value) || 0;
                    const budget = parseFloat(inp.getAttribute("data-budget")) || 0;
                    sum += w;
                    const preview = inp.closest("tr").querySelector(".root-target-preview");
                    if (preview) preview.textContent = ((budget * w) / 100).toFixed(2);
                });
                rootTotalEl.textContent = sum.toFixed(1) + "%";
                rootTotalEl.className = "tabular-nums " + (Math.abs(sum - 100) <= 0.01 ? "text-success" : "text-warning");
            }
            rootInputs.forEach((inp) => inp.addEventListener("input", recalcRoot));
        }

        const intInputs = document.querySelectorAll(".internal-weight-input");
        const intTotalEl = document.getElementById("internal-weight-total");
        if (intInputs.length && intTotalEl) {
            function recalcInt() {
                let sum = 0;
                intInputs.forEach(function (inp) {
                    const w = parseFloat(inp.value) || 0;
                    const pBudget = parseFloat(inp.getAttribute("data-parent-budget")) || 0;
                    sum += w;
                    const preview = inp.closest("tr").querySelector(".internal-time-preview");
                    if (preview) preview.textContent = ((pBudget * w) / 100).toFixed(2);
                });
                intTotalEl.textContent = sum.toFixed(1) + "%";
                intTotalEl.className = "tabular-nums " + (Math.abs(sum - 100) <= 0.01 ? "text-success" : "text-warning");
            }
            intInputs.forEach((inp) => inp.addEventListener("input", recalcInt));
        }
    }

    function initProgressModal() {
        const modalEl = document.getElementById("fc-progress-modal");
        if (!modalEl) return;
        const modal = new bootstrap.Modal(modalEl);
        const form = document.getElementById("fc-progress-form");
        const titleEl = document.getElementById("fc-progress-modal-title");
        const itemLabel = document.getElementById("fc-progress-item-label");
        const unitLabel = document.getElementById("fc-progress-unit-label");
        const qtyInput = document.getElementById("fc-progress-qty");
        const minsInput = document.getElementById("fc-progress-mins");
        const tsInput = document.getElementById("fc-progress-ts");
        const srcSelect = document.getElementById("fc-progress-source");
        const cmtInput = document.getElementById("fc-progress-comments");

        document.addEventListener("click", function (ev) {
            const addBtn = ev.target.closest(".fc-open-progress-btn");
            if (addBtn) {
                form.action = addBtn.getAttribute("data-action");
                titleEl.textContent = "Record Task Progress";
                itemLabel.textContent = addBtn.getAttribute("data-item-name") || "";
                unitLabel.textContent = addBtn.getAttribute("data-unit") || "units";
                qtyInput.value = "0";
                minsInput.value = "30";
                tsInput.value = "";
                srcSelect.value = "manual";
                cmtInput.value = "";
                modal.show();
                return;
            }
            const editBtn = ev.target.closest(".fc-edit-progress-btn");
            if (editBtn) {
                form.action = editBtn.getAttribute("data-action");
                titleEl.textContent = "Edit Progress Entry";
                itemLabel.textContent = editBtn.getAttribute("data-item-name") || "";
                unitLabel.textContent = editBtn.getAttribute("data-unit") || "units";
                qtyInput.value = editBtn.getAttribute("data-qty") || "0";
                minsInput.value = editBtn.getAttribute("data-mins") || "0";
                tsInput.value = editBtn.getAttribute("data-ts") || "";
                srcSelect.value = editBtn.getAttribute("data-source") || "manual";
                cmtInput.value = editBtn.getAttribute("data-comments") || "";
                modal.show();
            }
        });
    }

    let centeredChart = null;
    function renderCenteredChart() {
        const canvas = document.getElementById("centeredTaskChart");
        const data = window.CENTERED_TASK_CHART_DATA;
        if (!canvas || !data || !data.items || data.items.length === 0) return;

        const colors = window.fcChartColors();
        const activeItems = data.items.filter((i) => i.status !== "Archived");
        if (centeredChart) centeredChart.destroy();
        centeredChart = new Chart(canvas, {
            type: "bar",
            data: {
                labels: activeItems.map((i) => i.name),
                datasets: [
                    {
                        label: "Weight %",
                        data: activeItems.map((i) => i.weight_pct),
                        backgroundColor: data.accentColor || "#0ea5e9",
                        borderRadius: 5,
                    },
                    {
                        label: "Completion %",
                        data: activeItems.map((i) => i.completion_pct),
                        backgroundColor: data.primaryColor || "#4f46e5",
                        borderRadius: 5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, max: 100, ticks: { color: colors.text }, grid: { color: colors.grid } },
                    x: { ticks: { color: colors.text }, grid: { display: false } },
                },
                plugins: { legend: { labels: { color: colors.text } } },
            },
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initTaskFormBehavior();
        initAddItemTypeSwitch();
        initWeightLiveCalculators();
        initProgressModal();
        renderCenteredChart();
    });
    window.addEventListener("fc:themechange", renderCenteredChart);
})();
