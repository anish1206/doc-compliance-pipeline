document.addEventListener("DOMContentLoaded", () => {
    // ─── Element refs ────────────────────────────────────────────
    const uploadForm          = document.getElementById("uploadForm");
    const fileInput           = document.getElementById("fileInput");
    const dropArea            = document.getElementById("dropArea");
    const fileMsg             = document.getElementById("fileMsg");
    const statusMessage       = document.getElementById("statusMessage");
    const refreshBtn          = document.getElementById("refreshBtn");
    const documentsTableBody  = document.getElementById("documentsTableBody");
    const navHamburger        = document.getElementById("navHamburger");
    const navTray             = document.getElementById("navTray");

    // ─── Hamburger / Mobile Nav (optional) ───────────────────────
    if (navHamburger && navTray) {
        navHamburger.addEventListener("click", () => {
            const isOpen = navTray.classList.toggle("is-open");
            navHamburger.classList.toggle("is-open", isOpen);
            navHamburger.setAttribute("aria-expanded", isOpen);
            navTray.setAttribute("aria-hidden", !isOpen);
        });

        // Close tray when a tray link is tapped
        navTray.querySelectorAll(".nav-tray__link").forEach(link => {
            link.addEventListener("click", () => {
                navTray.classList.remove("is-open");
                navHamburger.classList.remove("is-open");
                navHamburger.setAttribute("aria-expanded", false);
                navTray.setAttribute("aria-hidden", true);
            });
        });
    }

    // ─── Drag & Drop ─────────────────────────────────────────────
    dropArea.addEventListener("click", () => fileInput.click());

    // Allow keyboard activation of drop area (role="button")
    dropArea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInput.click();
        }
    });

    dropArea.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropArea.classList.add("is-dragover");
    });

    dropArea.addEventListener("dragleave", () => {
        dropArea.classList.remove("is-dragover");
    });

    dropArea.addEventListener("drop", (e) => {
        e.preventDefault();
        dropArea.classList.remove("is-dragover");
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            fileInput.files = files;
            updateFileLabel(files[0].name);
        }
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            updateFileLabel(fileInput.files[0].name);
        }
    });

    function updateFileLabel(name) {
        fileMsg.innerHTML = `Selected: <strong>${name}</strong>`;
        dropArea.classList.add("has-file");
    }

    function resetFileLabel() {
        fileMsg.innerHTML = `Drag &amp; Drop PDF here or <strong>browse</strong>`;
        dropArea.classList.remove("has-file");
    }

    // ─── Upload & Scan ───────────────────────────────────────────
    // ─── Polling Helper for Asynchronous Processing ─────────────
    let pollInterval = null;
    function pollForUpdates(targetFilename) {
        if (pollInterval) clearInterval(pollInterval);
        let count = 0;
        pollInterval = setInterval(async () => {
            count++;
            const docs = await loadDocuments();
            if (docs && targetFilename) {
                const found = docs.find(d => d.filename === targetFilename);
                if (found) {
                    const isRestricted = found.classification === "RESTRICTED";
                    const statusType = isRestricted ? "error" : "success";
                    const statusPrefix = isRestricted ? "Alert!" : "Success!";
                    showStatus(
                        `${statusPrefix} Processing complete for <strong>${escapeHtml(targetFilename)}</strong> — Classified as: <strong>${escapeHtml(found.classification)}</strong>`,
                        statusType
                    );
                    clearInterval(pollInterval);
                    pollInterval = null;
                    return;
                }
            }
            if (count >= 10) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
        }, 1200);
    }

    // ─── Upload & Scan ───────────────────────────────────────────
    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!fileInput.files.length) return;

        const uploadBtn = document.getElementById("uploadBtn");
        uploadBtn.disabled = true;
        uploadBtn.textContent = "Dispatching…";

        const formData = new FormData();
        const selectedFile = fileInput.files[0];
        formData.append("file", selectedFile);

        showStatus(`Uploading <strong>${escapeHtml(selectedFile.name)}</strong> to inbox-bucket and queueing for scan…`, "info");

        try {
            const response = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                const targetName = result.filename || selectedFile.name;
                if (result.status === "QUEUED" || result.status === "PENDING") {
                    showStatus(
                        `Queued! File <strong>${escapeHtml(targetName)}</strong> is in the Redis queue. Background worker is scanning & redacting…`,
                        "info"
                    );
                    uploadForm.reset();
                    resetFileLabel();
                    pollForUpdates(targetName);
                } else if (result.data) {
                    const isRestricted = result.data.classification === "RESTRICTED";
                    const statusType = isRestricted ? "error" : "success";
                    const statusPrefix = isRestricted ? "Alert!" : "Success!";

                    showStatus(
                        `${statusPrefix} Processing complete for <strong>${escapeHtml(targetName)}</strong> — Classified as: <strong>${result.data.classification}</strong>`,
                        statusType
                    );
                    loadDocuments();
                    uploadForm.reset();
                    resetFileLabel();
                } else {
                    showStatus("File uploaded successfully.", "success");
                    loadDocuments();
                    uploadForm.reset();
                    resetFileLabel();
                }
            } else {
                showStatus(`Upload failed: ${result.error}`, "error");
            }
        } catch (error) {
            showStatus(`Network error: ${error.message}`, "error");
        } finally {
            uploadBtn.disabled = false;
            uploadBtn.textContent = "Upload & Scan Document";
        }
    });

    // ─── Load Documents from Firestore ───────────────────────────
    async function loadDocuments() {
        try {
            const response = await fetch("/api/documents");
            const data = await response.json();

            if (!data.documents || data.documents.length === 0) {
                documentsTableBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="empty-msg">
                            <div class="empty-state">
                                <svg class="empty-state__icon" width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <rect x="6" y="4" width="16" height="22" rx="2.5" stroke="#cccccc" stroke-width="1.5"/>
                                    <path d="M10 10H18M10 14H18M10 18H14" stroke="#cccccc" stroke-width="1.5" stroke-linecap="round"/>
                                </svg>
                                <p>No compliance logs found. Upload a file above!</p>
                            </div>
                        </td>
                    </tr>`;
                return [];
            }

            documentsTableBody.innerHTML = data.documents.map(doc => {
                const badgeClass  = doc.classification === "RESTRICTED"
                    ? "badge badge--restricted"
                    : "badge badge--public";
                const piiTags     = (doc.pii_detected || [])
                    .map(tag => `<span class="pii-tag">${escapeHtml(tag)}</span>`)
                    .join("") || "<span style='color:var(--color-ink-muted-48)'>None</span>";
                const fileSizeKB  = (doc.file_size_bytes / 1024).toFixed(1) + " KB";
                const dateStr     = doc.processed_at
                    ? new Date(doc.processed_at).toLocaleString()
                    : "N/A";

                const redactedName = doc.redacted_filename || (doc.public_path ? doc.public_path.split("/").pop() : `redacted_${doc.filename}`);
                const actionButtons = `
                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                        <a href="/api/view/${encodeURIComponent(redactedName)}" target="_blank" rel="noopener noreferrer" class="btn btn--utility btn--small" style="font-size:0.75rem; padding:4px 8px; display:inline-flex; align-items:center; text-decoration:none;" title="View redacted document in new tab">
                            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="margin-right:4px;">
                                <path d="M1 8s3-5.5 7-5.5S15 8 15 8s-3 5.5-7 5.5S1 8 1 8z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                                <circle cx="8" cy="8" r="2.5" stroke="currentColor" stroke-width="1.6"/>
                            </svg>
                            View
                        </a>
                        <a href="/api/download/${encodeURIComponent(redactedName)}" class="btn btn--utility btn--small" style="font-size:0.75rem; padding:4px 8px; display:inline-flex; align-items:center; text-decoration:none;" download title="Download redacted copy">
                            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" style="margin-right:4px;">
                                <path d="M7 1.5v7M4.5 6l2.5 2.5L9.5 6M2 11h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            Download
                        </a>
                    </div>
                `;

                return `
                    <tr>
                        <td><strong>${escapeHtml(doc.filename)}</strong></td>
                        <td><span class="${badgeClass}">${escapeHtml(doc.classification)}</span></td>
                        <td>${piiTags}</td>
                        <td>${fileSizeKB}</td>
                        <td>${dateStr}</td>
                        <td>${actionButtons}</td>
                    </tr>
                `;
            }).join("");

            return data.documents;

        } catch (error) {
            console.error("Failed to load documents:", error);
            documentsTableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="empty-msg">
                        <div class="empty-state">
                            <p style="color:var(--color-ink-muted-48)">Failed to load logs. Check your connection.</p>
                        </div>
                    </td>
                </tr>`;
            return [];
        }
    }

    refreshBtn.addEventListener("click", () => {
        // Animate the refresh icon
        const icon = refreshBtn.querySelector(".btn__icon");
        if (icon) {
            icon.style.transition = "transform 0.5s ease";
            icon.style.transform  = "rotate(360deg)";
            setTimeout(() => {
                icon.style.transition = "";
                icon.style.transform  = "";
            }, 500);
        }
        loadDocuments();
    });

    // ─── Status Helper ────────────────────────────────────────────
    function showStatus(message, type) {
        statusMessage.className = `status-message ${type}`;
        statusMessage.innerHTML  = message;
    }

    // ─── XSS Guard ────────────────────────────────────────────────
    function escapeHtml(str) {
        if (typeof str !== "string") return String(str);
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // ─── Initial Load ─────────────────────────────────────────────
    loadDocuments();
});