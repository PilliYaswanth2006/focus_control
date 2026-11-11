(function () {
    "use strict";
    let taskChart = null;
    let weeklyHoursChart = null;
    let urgeChart = null;

    function renderCharts() {
        const data = window.DASHBOARD_DATA || {};
        const colors = window.fcChartColors();

        const taskCanvas = document.getElementById("dashTaskChart");
        if (taskCanvas && data.rootTasks && data.rootTasks.length > 0) {
            if (taskChart) taskChart.destroy();
            taskChart = new Chart(taskCanvas, {
                type: "bar",
                data: {
                    labels: data.rootTasks.map((t) => t.name),
                    datasets: [
                        {
                            label: "Completion %",
                            data: data.rootTasks.map((t) => t.completion_pct),
                            backgroundColor: data.rootTasks.map((t) => t.color || "#4f46e5"),
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            ticks: { color: colors.text },
                            grid: { color: colors.grid },
                        },
                        x: {
                            ticks: { color: colors.text },
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                    },
                },
            });
        }

        const weeklyCanvas = document.getElementById("dashWeeklyHoursChart");
        if (weeklyCanvas && data.weeklyTaskHours && data.weeklyTaskHours.length > 0) {
            if (weeklyHoursChart) weeklyHoursChart.destroy();
            weeklyHoursChart = new Chart(weeklyCanvas, {
                type: "bar",
                data: {
                    labels: data.weeklyTaskHours.map((d) => d.date.slice(5)),
                    datasets: [
                        {
                            label: "Focus Hours",
                            data: data.weeklyTaskHours.map((d) => d.hours),
                            backgroundColor: "#0ea5e9",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { color: colors.text },
                            grid: { color: colors.grid },
                        },
                        x: {
                            ticks: { color: colors.text },
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                    },
                },
            });
        }

        const urgeCanvas = document.getElementById("dashUrgeChart");
        if (urgeCanvas && data.urgeTrend && data.urgeTrend.length > 0) {
            if (urgeChart) urgeChart.destroy();
            urgeChart = new Chart(urgeCanvas, {
                type: "line",
                data: {
                    labels: data.urgeTrend.map((d) => d.date),
                    datasets: [
                        {
                            label: "Resisted Urges",
                            data: data.urgeTrend.map((d) => d.resisted),
                            borderColor: "#10b981",
                            backgroundColor: "rgba(16, 185, 129, 0.14)",
                            fill: true,
                            tension: 0.3,
                        },
                        {
                            label: "Gave-In Urges",
                            data: data.urgeTrend.map((d) => d.gave_in),
                            borderColor: "#e11d48",
                            backgroundColor: "rgba(225, 29, 72, 0.12)",
                            fill: true,
                            tension: 0.3,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0, color: colors.text },
                            grid: { color: colors.grid },
                        },
                        x: {
                            ticks: { color: colors.text },
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: { labels: { color: colors.text } },
                    },
                },
            });
        }
    }

    document.addEventListener("DOMContentLoaded", renderCharts);
    window.addEventListener("fc:themechange", renderCharts);
})();
