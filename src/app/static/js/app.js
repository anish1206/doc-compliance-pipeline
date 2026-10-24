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
    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!fileInput.files.length) return;

        const uploadBtn = document.getElementById("uploadBtn");
        uploadBtn.disabled = true;
        uploadBtn.textContent = "Scanning…";

        const formData = new FormData();
        formData.append("file", fileInput.files[0]);

        showStatus("Uploading &amp; scanning document via serverless engine…", "info");

        try {
            const response = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                const isRestricted = result.data.classification === "RESTRICTED";
                const statusType = isRestricted ? "error" : "success";
                const statusPrefix = isRestricted ? "Warning!" : "Success!";

                showStatus(
                    `${statusPrefix} Document classified as: <strong>${result.data.classification}</strong>`,
                    statusType
                );
                loadDocuments();
                uploadForm.reset();
                resetFileLabel();
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
        // Show a loading skeleton row
        documentsTableBody.innerHTML = `
            <tr>
                <td colspan="5" class="empty-msg">
                    <div class="empty-state">
                        <svg class="empty-state__icon" width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                            <rect x="6" y="4" width="16" height="22" rx="2.5" stroke="#cccccc" stroke-width="1.5"/>
                            <path d="M10 10H18M10 14H18M10 18H14" stroke="#cccccc" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                        <p>Loading compliance logs from Cloud Firestore…</p>
                    </div>
                </td>
            </tr>`;

        try {
            const response = await fetch("/api/documents");
            const data = await response.json();

            if (!data.documents || data.documents.length === 0) {
                documentsTableBody.innerHTML = `
                    <tr>
                        <td colspan="5" class="empty-msg">
                            <div class="empty-state">
                                <svg class="empty-state__icon" width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <rect x="6" y="4" width="16" height="22" rx="2.5" stroke="#cccccc" stroke-width="1.5"/>
                                    <path d="M10 10H18M10 14H18M10 18H14" stroke="#cccccc" stroke-width="1.5" stroke-linecap="round"/>
                                </svg>
                                <p>No compliance logs found. Upload a file above!</p>
                            </div>
                        </td>
                    </tr>`;
                return;
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

                return `
                    <tr>
                        <td><strong>${escapeHtml(doc.filename)}</strong></td>
                        <td><span class="${badgeClass}">${escapeHtml(doc.classification)}</span></td>
                        <td>${piiTags}</td>
                        <td>${fileSizeKB}</td>
                        <td>${dateStr}</td>
                    </tr>
                `;
            }).join("");

        } catch (error) {
            console.error("Failed to load documents:", error);
            documentsTableBody.innerHTML = `
                <tr>
                    <td colspan="5" class="empty-msg">
                        <div class="empty-state">
                            <p style="color:var(--color-ink-muted-48)">Failed to load logs. Check your connection.</p>
                        </div>
                    </td>
                </tr>`;
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