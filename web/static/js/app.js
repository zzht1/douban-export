/* ── Douban Insight 前端逻辑 ─────────────────────── */

const PHASE_LABELS = {
    queued: "排队中",
    scraping_movie: "爬取电影数据",
    scraping_book: "爬取图书数据",
    scraping_music: "爬取音乐数据",
    scraping: "爬取数据",
    scraping_done: "爬取完成",
    analyzing: "分析数据",
    generating_report: "生成报告",
    done: "完成",
    error: "出错",
};

const STAGE_ORDER = [
    "scraping_movie",
    "scraping_book",
    "scraping_music",
    "analyzing",
    "generating_report",
];

let currentTaskId = null;
let pollTimer = null;

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("analyze-form");
    if (form) {
        form.addEventListener("submit", handleSubmit);
    }
    // Enter key support
    const input = document.getElementById("user-input");
    if (input) {
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                form.dispatchEvent(new Event("submit"));
            }
        });
    }
});

async function handleSubmit(e) {
    e.preventDefault();

    const userInput = document.getElementById("user-input").value.trim();
    const cookieInput = document.getElementById("cookie-input")?.value.trim() || "";

    if (!userInput) return;

    const btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.querySelector(".btn-text").style.display = "none";
    btn.querySelector(".btn-loading").style.display = "inline";

    const progressPanel = document.getElementById("progress-panel");
    const errorPanel = document.getElementById("error-panel");
    progressPanel.style.display = "block";
    errorPanel.style.display = "none";

    try {
        const resp = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user: userInput, cookie: cookieInput }),
        });

        const data = await resp.json();

        if (data.error) {
            showError(data.error);
            resetButton();
            return;
        }

        currentTaskId = data.task_id;

        if (data.status === "done") {
            const phaseLabel = document.getElementById("phase-label");
            const activityText = document.getElementById("activity-text");
            if (phaseLabel) phaseLabel.textContent = "完成";
            if (activityText) activityText.textContent = "使用缓存数据";
            document.querySelectorAll(".phase-node").forEach(n => n.classList.add("done"));
            document.querySelectorAll(".phase-connector").forEach(c => c.classList.add("done"));
            setTimeout(() => {
                window.location.href = `/report/${data.task_id}`;
            }, 600);
            return;
        }

        startPolling();
    } catch (err) {
        showError("网络错误，请检查服务是否运行");
        resetButton();
    }
}

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 1500);
    pollStatus();
}

async function pollStatus() {
    if (!currentTaskId) return;

    try {
        const resp = await fetch(`/api/status/${currentTaskId}`);
        const data = await resp.json();

        updateProgress(data);

        if (data.status === "done") {
            clearInterval(pollTimer);
            pollTimer = null;
            setTimeout(() => {
                window.location.href = `/report/${currentTaskId}`;
            }, 800);
        } else if (data.status === "error") {
            clearInterval(pollTimer);
            pollTimer = null;
            showError(data.error || "分析过程中出错");
            resetButton();
        }
    } catch (err) {
        console.warn("Poll error:", err);
    }
}

function updateProgress(data) {
    const phaseLabel = document.getElementById("phase-label");
    const activityText = document.getElementById("activity-text");
    const logArea = document.getElementById("log-area");

    phaseLabel.textContent = PHASE_LABELS[data.phase] || data.phase || "处理中";

    // 更新活动指示器文字
    if (data.message) {
        activityText.textContent = data.message;
    }

    updateStages(data.phase);

    if (data.logs && data.logs.length > 0) {
        logArea.innerHTML = "";
        for (const log of data.logs.slice(-8)) {
            const entry = document.createElement("div");
            entry.className = "log-entry";
            entry.innerHTML = `<span class="log-time">${log.time}</span>${log.message}`;
            logArea.appendChild(entry);
        }
        logArea.scrollTop = logArea.scrollHeight;
    }
}

function updateStages(currentPhase) {
    const nodes = document.querySelectorAll(".phase-node");
    const connectors = document.querySelectorAll(".phase-connector");
    const stageNames = STAGE_ORDER;
    const currentIdx = stageNames.indexOf(currentPhase);

    nodes.forEach((node) => {
        node.classList.remove("active", "done");
        const stage = node.dataset.stage;
        const idx = stageNames.indexOf(stage);

        if (currentPhase === "done") {
            node.classList.add("done");
        } else if (currentIdx > idx || (currentPhase === "scraping_done" && idx < 3)) {
            node.classList.add("done");
        } else if (currentIdx === idx) {
            node.classList.add("active");
        }
    });

    connectors.forEach((conn, i) => {
        conn.classList.remove("active", "done");
        if (currentPhase === "done") {
            conn.classList.add("done");
        } else if (currentIdx > i) {
            conn.classList.add("done");
        } else if (currentIdx === i) {
            conn.classList.add("active");
        }
    });
}

function showError(message) {
    const errorPanel = document.getElementById("error-panel");
    const errorMsg = document.getElementById("error-message");
    const progressPanel = document.getElementById("progress-panel");

    progressPanel.style.display = "none";
    errorPanel.style.display = "block";
    errorMsg.textContent = message;
}

function resetButton() {
    const btn = document.getElementById("submit-btn");
    if (btn) {
        btn.disabled = false;
        btn.querySelector(".btn-text").style.display = "inline";
        btn.querySelector(".btn-loading").style.display = "none";
    }
}

function showCookieHelp() {
    document.getElementById("cookie-help-modal").style.display = "flex";
}

function hideCookieHelp() {
    document.getElementById("cookie-help-modal").style.display = "none";
}

// ── 删除数据（隐私权利） ───────────────────

async function showDeleteDialog() {
    const userId = prompt("请输入要删除数据的豆瓣用户 ID：");
    if (!userId || !userId.trim()) return;

    const uid = userId.trim();

    // 先检查是否有数据
    try {
        const infoResp = await fetch(`/api/data/${uid}`);
        const info = await infoResp.json();

        if (!info.exists) {
            alert(`未找到用户「${uid}」的缓存数据。`);
            return;
        }

        const msg = `确定要删除用户「${uid}」的所有缓存数据吗？\n\n` +
            `· 文件数：${info.file_count}\n` +
            `· 数据大小：${info.total_size_kb} KB\n` +
            `· 最后更新：${info.last_modified}\n\n` +
            `此操作不可撤销。`;

        if (!confirm(msg)) return;

        const delResp = await fetch(`/api/data/${uid}`, { method: "DELETE" });
        const result = await delResp.json();

        if (result.deleted) {
            alert(`用户「${uid}」的所有数据已删除。`);
        } else {
            alert("删除失败，请稍后重试。");
        }
    } catch (e) {
        alert("请求失败：" + e.message);
    }
}
