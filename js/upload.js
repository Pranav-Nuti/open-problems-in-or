/**
 * Upload page: login/register + PDF intake + extract jobs + admin approvals.
 *
 * Talks to SITE_CONFIG.uploadApiBaseUrl:
 *   POST {base}/auth/login | /auth/register
 *   GET  {base}/auth/pending  (admin)
 *   POST {base}/auth/pending/{id}/approve|reject  (admin)
 *   POST/GET {base}/api/uploads
 *   GET  {base}/api/uploads/{id}/file
 *   POST {base}/api/uploads/{id}/jobs  {kind:"extract"|"pipeline"}
 */
(function () {
  "use strict";

  const SESSION_KEY = "opor_upload_session_v1";
  const config = window.SITE_CONFIG || {};
  const apiBase = String(config.uploadApiBaseUrl || "").replace(/\/$/, "");
  let pollTimer = null;

  const els = {
    banner: document.getElementById("upload-status-banner"),
    authPanel: document.getElementById("auth-panel"),
    loginPanel: document.getElementById("login-panel"),
    registerPanel: document.getElementById("register-panel"),
    registerPendingPanel: document.getElementById("register-pending-panel"),
    registerPendingMessage: document.getElementById("register-pending-message"),
    authTabLogin: document.getElementById("auth-tab-login"),
    authTabRegister: document.getElementById("auth-tab-register"),
    uploadPanel: document.getElementById("upload-panel"),
    loginForm: document.getElementById("login-form"),
    loginError: document.getElementById("login-error"),
    loginSubmit: document.getElementById("login-submit"),
    registerForm: document.getElementById("register-form"),
    registerError: document.getElementById("register-error"),
    registerSubmit: document.getElementById("register-submit"),
    registerBackToLogin: document.getElementById("register-back-to-login"),
    sessionLabel: document.getElementById("session-label"),
    logoutBtn: document.getElementById("logout-btn"),
    adminPendingPanel: document.getElementById("admin-pending-panel"),
    pendingList: document.getElementById("pending-list"),
    pendingEmpty: document.getElementById("pending-empty"),
    pendingError: document.getElementById("pending-error"),
    pendingRefreshBtn: document.getElementById("pending-refresh-btn"),
    dropzone: document.getElementById("upload-dropzone"),
    fileInput: document.getElementById("upload-file-input"),
    uploadError: document.getElementById("upload-error"),
    uploadList: document.getElementById("upload-list"),
    uploadEmpty: document.getElementById("upload-empty"),
    resultsList: document.getElementById("results-list"),
    resultsEmpty: document.getElementById("results-empty"),
    clearUploadsBtn: document.getElementById("clear-uploads-btn"),
    clearResultsBtn: document.getElementById("clear-results-btn"),
  };

  function isSourceKind(item) {
    const kind = (item && item.kind) || "source";
    if (kind !== "source") return false;
    // Fallbacks if an older API row omitted kind.
    if (item && item.parent_upload_id) return false;
    if (String((item && item.status) || "").toLowerCase() === "extracted") return false;
    return true;
  }

  function kindLabel(kind) {
    if (kind === "extraction" || kind === "extracted") return "extraction";
    if (kind === "literature_review") return "literature review";
    if (kind === "solver_verified") return "verified solution";
    if (kind === "solver_partial" || kind === "solver_attempt" || kind === "solve_report") {
      return "unsuccessful attempt";
    }
    return kind || "output";
  }

  function apiConfigured() {
    return Boolean(apiBase);
  }

  function loadSession() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_err) {
      return null;
    }
  }

  function saveSession(session) {
    if (!session) {
      sessionStorage.removeItem(SESSION_KEY);
      return;
    }
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  }

  function setBanner(text, state) {
    if (!els.banner) return;
    els.banner.textContent = text;
    els.banner.classList.toggle("is-connected", state === "connected");
    els.banner.classList.toggle("is-scaffold", state === "scaffold");
  }

  function setError(node, message) {
    if (node) node.textContent = message || "";
  }

  function authHeaders(session) {
    const headers = { Accept: "application/json" };
    if (session && session.token) {
      headers.Authorization = `Bearer ${session.token}`;
    }
    return headers;
  }

  async function apiFetch(path, options = {}, session) {
    if (!apiConfigured()) {
      const err = new Error(
        "Upload backend is not configured yet (SITE_CONFIG.uploadApiBaseUrl is empty)."
      );
      err.code = "SCAFFOLD";
      throw err;
    }
    const opts = { ...options, credentials: "include" };
    opts.headers = { ...authHeaders(session), ...(options.headers || {}) };
    const res = await fetch(`${apiBase}${path}`, opts);
    let body = null;
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      body = await res.json();
    } else {
      body = await res.text();
    }
    if (!res.ok) {
      let detail =
        (body && body.detail) ||
        (body && body.message) ||
        (typeof body === "string" ? body : "") ||
        res.statusText;
      if (Array.isArray(detail)) {
        detail = detail
          .map((item) => (item && item.msg) || JSON.stringify(item))
          .filter(Boolean)
          .join("; ");
      } else if (detail && typeof detail === "object") {
        detail = detail.msg || JSON.stringify(detail);
      }
      const err = new Error(detail || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function isAdminSession(session) {
    return Boolean(session && String(session.role || "").toLowerCase() === "admin");
  }

  function showAuthMode(mode) {
    const login = mode === "login";
    const register = mode === "register";
    const pending = mode === "pending";
    if (els.loginPanel) els.loginPanel.hidden = !login;
    if (els.registerPanel) els.registerPanel.hidden = !register;
    if (els.registerPendingPanel) els.registerPendingPanel.hidden = !pending;
    if (els.authTabLogin) {
      els.authTabLogin.classList.toggle("is-active", login || pending);
      els.authTabLogin.setAttribute("aria-selected", login || pending ? "true" : "false");
    }
    if (els.authTabRegister) {
      els.authTabRegister.classList.toggle("is-active", register);
      els.authTabRegister.setAttribute("aria-selected", register ? "true" : "false");
    }
  }

  function renderSession(session) {
    const signedIn = Boolean(session && session.username && session.token);
    if (els.authPanel) els.authPanel.hidden = signedIn;
    els.uploadPanel.hidden = !signedIn;
    if (signedIn) {
      const role = session.role ? ` (${session.role})` : "";
      els.sessionLabel.textContent = `Signed in as ${session.username}${role}`;
      if (els.adminPendingPanel) els.adminPendingPanel.hidden = !isAdminSession(session);
    } else if (els.adminPendingPanel) {
      els.adminPendingPanel.hidden = true;
    }
    setError(els.loginError, "");
    setError(els.uploadError, "");
    setError(els.registerError, "");
    setError(els.pendingError, "");
  }

  function formatUploadDate(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
  }

  function statusPill(status) {
    const pill = document.createElement("span");
    pill.className = "upload-status-pill";
    const key = String(status || "").toLowerCase();
    if (
      key === "extracted" ||
      key === "done" ||
      key === "verified" ||
      key === "solved" ||
      key.startsWith("review")
    ) {
      pill.classList.add("is-reviewed");
    } else if (key === "partial") {
      pill.classList.add("is-partial");
    } else if (key === "failed" || key === "error") {
      pill.classList.add("is-failed");
    } else if (
      key === "queued" ||
      key === "running" ||
      key.startsWith("pending") ||
      key.startsWith("process")
    ) {
      pill.classList.add("is-pending");
    }
    pill.textContent = status;
    return pill;
  }

  function latestJob(item) {
    const jobs = Array.isArray(item.jobs) ? item.jobs : [];
    return jobs.length ? jobs[0] : null;
  }

  function hasActiveJob(items) {
    return (items || []).some((item) => {
      const job = latestJob(item);
      return job && (job.status === "queued" || job.status === "running");
    });
  }

  function stageStateLabel(state) {
    const key = String(state || "pending").toLowerCase();
    if (key === "done" || key === "verified") return key === "verified" ? "Verified" : "Done";
    if (key === "partial") return "Partial";
    if (key === "running") return "Running";
    if (key === "failed") return "Failed";
    if (key === "skipped") return "Skipped";
    if (key === "queued") return "Queued";
    return "Waiting";
  }

  function stagePill(label, state) {
    const pill = document.createElement("span");
    const key = String(state || "pending").toLowerCase();
    pill.className = "upload-stage-pill";
    if (key === "done" || key === "verified") pill.classList.add("is-done");
    else if (key === "partial") pill.classList.add("is-partial");
    else if (key === "running") pill.classList.add("is-running");
    else if (key === "failed") pill.classList.add("is-failed");
    else if (key === "skipped") pill.classList.add("is-skipped");
    else pill.classList.add("is-waiting");
    pill.textContent = `${label}: ${stageStateLabel(key)}`;
    return pill;
  }

  function stageTrack(job) {
    if (!job) return null;
    const row = document.createElement("div");
    row.className = "upload-stage-track";
    row.setAttribute("aria-label", "Pipeline stage progress");

    const kind = job.kind || "extract";
    if (kind === "pipeline") {
      const s = job.stages && typeof job.stages === "object" ? job.stages : {};
      // Infer while queued before worker writes stages.
      const extraction =
        s.extraction || (job.status === "queued" ? "pending" : job.status === "failed" ? "failed" : "pending");
      const review = s.literature_review || "pending";
      const solver = s.solver || "pending";
      row.appendChild(stagePill("Extract", extraction));
      row.appendChild(stagePill("Review", review));
      row.appendChild(stagePill("Solve", solver));
      return row;
    }

    // Extract-only job: one stage mirroring job status.
    let state = "pending";
    if (job.status === "queued") state = "queued";
    else if (job.status === "running") state = "running";
    else if (job.status === "done") state = "done";
    else if (job.status === "failed") state = "failed";
    row.appendChild(stagePill("Extract", state));
    return row;
  }

  function downloadHref(uploadId) {
    return `${apiBase}/api/uploads/${uploadId}/file`;
  }

  async function downloadUpload(uploadId, session) {
    const res = await fetch(downloadHref(uploadId), {
      headers: authHeaders(session),
      credentials: "include",
    });
    if (!res.ok) {
      throw new Error(`Download failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `upload-${uploadId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function startExtract(uploadId, session, button) {
    setError(els.uploadError, "");
    if (button) button.disabled = true;
    try {
      await apiFetch(
        `/api/uploads/${uploadId}/jobs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "extract" }),
        },
        session
      );
      await refreshUploads(session);
    } catch (err) {
      setError(els.uploadError, err.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function startPipeline(uploadId, session, button) {
    setError(els.uploadError, "");
    const ok = window.confirm(
      "Run the full pipeline on this paper?\n\n" +
        "1) Extract open problem\n" +
        "2) Literature review (web search)\n" +
        "3) One-pass solve-base only if review says still open\n\n" +
        "Verified solutions and unsuccessful attempts are stored separately.\n" +
        "This can take a long time and incurs model cost."
    );
    if (!ok) return;
    if (button) button.disabled = true;
    try {
      await apiFetch(
        `/api/uploads/${uploadId}/jobs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "pipeline" }),
        },
        session
      );
      await refreshUploads(session);
    } catch (err) {
      setError(els.uploadError, err.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function cancelJob(jobId, session, button) {
    setError(els.uploadError, "");
    if (button) button.disabled = true;
    try {
      await apiFetch(`/api/jobs/${jobId}/cancel`, { method: "POST" }, session);
      await refreshUploads(session);
    } catch (err) {
      setError(els.uploadError, err.message);
      if (button) button.disabled = false;
    }
  }

  async function clearList(scope, session, button) {
    setError(els.uploadError, "");
    const label = scope === "sources" ? "uploaded papers" : "run outputs";
    const ok = window.confirm(
      `Clear all ${label} from this list?\n\n` +
        "They disappear from the page, but nothing is deleted on the server" +
        (scope === "sources"
          ? "; papers with an active job are kept."
          : "; outputs of a run still in progress are kept.")
    );
    if (!ok) return;
    if (button) button.disabled = true;
    try {
      const res = await apiFetch(
        "/api/uploads/archive",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope }),
        },
        session
      );
      await refreshUploads(session);
      if (res && res.skipped_active) {
        setError(
          els.uploadError,
          `Cleared ${res.archived}; kept ${res.skipped_active} with an active job.`
        );
      }
    } catch (err) {
      setError(els.uploadError, err.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function stageSummary(job) {
    if (!job) return "";
    const kind = job.kind || "extract";
    if (kind === "pipeline") return "pipeline";
    return kind;
  }

  function renderList(targetList, emptyNode, items, session, mode, parentNames) {
    if (!targetList || !emptyNode) return;
    targetList.innerHTML = "";
    if (!items.length) {
      emptyNode.hidden = false;
      targetList.hidden = true;
      return;
    }
    emptyNode.hidden = true;
    targetList.hidden = false;

    for (const item of items) {
      const li = document.createElement("li");
      li.className = "upload-list-item";

      const kind = item.kind || "source";
      const main = document.createElement("div");
      main.className = "upload-list-main";

      const name = document.createElement("span");
      name.className = "upload-list-name";
      const label = item.filename || item.name || "upload.pdf";
      if (mode === "results") {
        name.textContent = `${label} (${kindLabel(kind)})`;
      } else {
        name.textContent = label;
      }

      const meta = document.createElement("span");
      meta.className = "upload-list-meta";
      const job = latestJob(item);
      const bits = [formatUploadDate(item.uploaded_at || item.created_at || "")];
      if (mode === "results" && item.parent_upload_id) {
        const parentName = parentNames && parentNames[item.parent_upload_id];
        bits.push(parentName ? `from ${parentName}` : `from upload #${item.parent_upload_id}`);
      }
      if (mode === "sources" && job) {
        bits.push(stageSummary(job));
        if (job.error_message) bits.push(String(job.error_message).slice(0, 100));
      }
      meta.textContent = bits.filter(Boolean).join(" · ");

      main.appendChild(name);
      main.appendChild(meta);
      if (mode === "sources" && job) {
        const track = stageTrack(job);
        if (track) main.appendChild(track);
      }

      let status = String(item.status || "received").trim() || "received";
      if (mode === "sources" && job) status = job.status;

      li.appendChild(main);
      li.appendChild(statusPill(status));

      const actions = document.createElement("div");
      actions.className = "upload-list-actions";

      const dl = document.createElement("button");
      dl.type = "button";
      dl.className = "upload-btn upload-btn-secondary";
      dl.textContent = "Download";
      dl.addEventListener("click", async () => {
        try {
          await downloadUpload(item.id, session);
        } catch (err) {
          setError(els.uploadError, err.message);
        }
      });
      actions.appendChild(dl);

      if (mode === "sources") {
        const active = job && (job.status === "queued" || job.status === "running");
        const extractBtn = document.createElement("button");
        extractBtn.type = "button";
        extractBtn.className = "upload-btn upload-btn-secondary";
        extractBtn.textContent = active && job.kind === "extract" ? "Extracting…" : "Extract";
        extractBtn.disabled = Boolean(active);
        extractBtn.addEventListener("click", () => startExtract(item.id, session, extractBtn));
        actions.appendChild(extractBtn);

        const pipeBtn = document.createElement("button");
        pipeBtn.type = "button";
        pipeBtn.className = "upload-btn";
        pipeBtn.textContent =
          active && job.kind === "pipeline" ? "Pipeline running…" : "Run pipeline";
        pipeBtn.disabled = Boolean(active);
        pipeBtn.addEventListener("click", () => startPipeline(item.id, session, pipeBtn));
        actions.appendChild(pipeBtn);

        if (active && job.id != null) {
          const cancelBtn = document.createElement("button");
          cancelBtn.type = "button";
          cancelBtn.className = "upload-btn upload-btn-secondary";
          cancelBtn.textContent = "Cancel";
          cancelBtn.addEventListener("click", () => cancelJob(job.id, session, cancelBtn));
          actions.appendChild(cancelBtn);
        }
      }

      li.appendChild(actions);
      targetList.appendChild(li);
    }
  }

  function renderUploads(items, session) {
    const list = Array.isArray(items) ? items : [];
    const sources = list.filter((item) => isSourceKind(item));
    const results = list.filter((item) => !isSourceKind(item));
    const parentNames = Object.create(null);
    for (const src of sources) {
      parentNames[src.id] = src.filename || src.name || `upload #${src.id}`;
    }

    renderList(els.uploadList, els.uploadEmpty, sources, session, "sources", parentNames);
    renderList(els.resultsList, els.resultsEmpty, results, session, "results", parentNames);

    if (els.clearUploadsBtn) els.clearUploadsBtn.hidden = !sources.length;
    if (els.clearResultsBtn) els.clearResultsBtn.hidden = !results.length;

    if (hasActiveJob(sources)) {
      startPolling(session);
    } else {
      stopPolling();
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling(session) {
    if (pollTimer) return;
    pollTimer = setInterval(() => {
      refreshUploads(session, true);
    }, 3000);
  }

  async function refreshUploads(session, quiet) {
    if (!apiConfigured()) {
      renderUploads([], session);
      return;
    }
    try {
      const data = await apiFetch("/api/uploads", { method: "GET" }, session);
      renderUploads(data.items || data.uploads || data || [], session);
      if (!quiet) setError(els.uploadError, "");
    } catch (err) {
      if (err.status === 401) {
        saveSession(null);
        renderSession(null);
        stopPolling();
      }
      if (!quiet) setError(els.uploadError, err.message);
    }
  }

  async function handleLogin(event) {
    event.preventDefault();
    setError(els.loginError, "");
    const username = String(els.loginForm.username.value || "").trim();
    const password = String(els.loginForm.password.value || "");
    if (!username || !password) {
      setError(els.loginError, "Enter a username and password.");
      return;
    }

    els.loginSubmit.disabled = true;
    try {
      const data = await apiFetch(
        "/auth/login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        },
        null
      );
      const user = data.user || {};
      const session = {
        username: user.username || data.username || username,
        role: user.role || null,
        token: data.token || data.access_token || null,
      };
      saveSession(session);
      renderSession(session);
      els.loginForm.reset();
      await refreshUploads(session);
      if (isAdminSession(session)) await refreshPending(session);
    } catch (err) {
      setError(els.loginError, err.message);
    } finally {
      els.loginSubmit.disabled = false;
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    setError(els.registerError, "");
    if (!els.registerForm) return;
    const username = String(els.registerForm.username.value || "").trim();
    const email = String(els.registerForm.email.value || "").trim();
    const password = String(els.registerForm.password.value || "");
    if (!username || !email || !password) {
      setError(els.registerError, "Enter a username, email, and password.");
      return;
    }
    if (els.registerSubmit) els.registerSubmit.disabled = true;
    try {
      const data = await apiFetch(
        "/auth/register",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, email, password }),
        },
        null
      );
      els.registerForm.reset();
      if (els.registerPendingMessage) {
        els.registerPendingMessage.textContent =
          (data && data.message) ||
          `Account “${username}” was created and is pending approval. An admin must approve it before you can sign in.`;
      }
      showAuthMode("pending");
    } catch (err) {
      setError(els.registerError, err.message);
    } finally {
      if (els.registerSubmit) els.registerSubmit.disabled = false;
    }
  }

  async function refreshPending(session, quiet) {
    if (!els.adminPendingPanel || !isAdminSession(session)) return;
    try {
      const data = await apiFetch("/auth/pending", { method: "GET" }, session);
      renderPending(data.items || [], session);
      if (!quiet) setError(els.pendingError, "");
    } catch (err) {
      if (err.status === 401 || err.status === 403) {
        if (els.adminPendingPanel) els.adminPendingPanel.hidden = true;
      }
      if (!quiet) setError(els.pendingError, err.message);
    }
  }

  function renderPending(items, session) {
    if (!els.pendingList || !els.pendingEmpty) return;
    const list = Array.isArray(items) ? items : [];
    els.pendingList.innerHTML = "";
    if (!list.length) {
      els.pendingEmpty.hidden = false;
      els.pendingList.hidden = true;
      return;
    }
    els.pendingEmpty.hidden = true;
    els.pendingList.hidden = false;
    for (const item of list) {
      const li = document.createElement("li");
      li.className = "upload-list-item";

      const main = document.createElement("div");
      main.className = "upload-list-main";
      const name = document.createElement("span");
      name.className = "upload-list-name";
      name.textContent = item.username || `user #${item.id}`;
      const meta = document.createElement("span");
      meta.className = "upload-list-meta";
      const bits = [item.email || "", formatUploadDate(item.created_at || "")].filter(Boolean);
      meta.textContent = bits.join(" · ");
      main.appendChild(name);
      main.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "upload-list-actions";

      const approveBtn = document.createElement("button");
      approveBtn.type = "button";
      approveBtn.className = "upload-btn";
      approveBtn.textContent = "Approve";
      approveBtn.addEventListener("click", () =>
        decidePending(item.id, "approve", session, approveBtn)
      );

      const rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "upload-btn upload-btn-secondary";
      rejectBtn.textContent = "Reject";
      rejectBtn.addEventListener("click", () =>
        decidePending(item.id, "reject", session, rejectBtn)
      );

      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      li.appendChild(main);
      li.appendChild(statusPill("pending"));
      li.appendChild(actions);
      els.pendingList.appendChild(li);
    }
  }

  async function decidePending(userId, action, session, button) {
    setError(els.pendingError, "");
    if (button) button.disabled = true;
    try {
      await apiFetch(`/auth/pending/${userId}/${action}`, { method: "POST" }, session);
      await refreshPending(session);
    } catch (err) {
      setError(els.pendingError, err.message);
      if (button) button.disabled = false;
    }
  }

  async function handleLogout() {
    const session = loadSession();
    setError(els.uploadError, "");
    stopPolling();
    try {
      if (apiConfigured()) {
        await apiFetch("/auth/logout", { method: "POST" }, session);
      }
    } catch (_err) {
      // Still clear local session.
    }
    saveSession(null);
    renderSession(null);
    showAuthMode("login");
    renderUploads([]);
    renderPending([]);
  }

  async function handleFile(file) {
    setError(els.uploadError, "");
    if (!file) return;
    if (file.type && file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) {
      setError(els.uploadError, "Only PDF files are accepted.");
      return;
    }
    const session = loadSession();
    if (!session) {
      setError(els.uploadError, "Sign in to upload.");
      return;
    }

    els.dropzone.classList.add("is-uploading");
    try {
      const body = new FormData();
      body.append("file", file, file.name);
      await apiFetch(
        "/api/uploads",
        {
          method: "POST",
          body,
          headers: session.token ? { Authorization: `Bearer ${session.token}` } : {},
        },
        session
      );
      await refreshUploads(session);
    } catch (err) {
      setError(els.uploadError, err.message);
    } finally {
      els.dropzone.classList.remove("is-uploading");
      els.fileInput.value = "";
    }
  }

  function wireDropzone() {
    const openPicker = () => {
      if (els.dropzone.classList.contains("is-uploading")) return;
      els.fileInput.click();
    };
    els.dropzone.addEventListener("click", openPicker);
    els.dropzone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPicker();
      }
    });
    els.fileInput.addEventListener("change", () => {
      const file = els.fileInput.files && els.fileInput.files[0];
      handleFile(file);
    });
    ["dragenter", "dragover"].forEach((name) => {
      els.dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        els.dropzone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((name) => {
      els.dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        els.dropzone.classList.remove("is-dragover");
      });
    });
    els.dropzone.addEventListener("drop", (event) => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      handleFile(file);
    });
  }

  async function boot() {
    if (apiConfigured()) {
      setBanner(`Connected to upload API at ${apiBase}`, "connected");
    } else {
      setBanner(
        "Scaffold mode: set SITE_CONFIG.uploadApiBaseUrl in js/site-config.js to enable login and uploads against the backend.",
        "scaffold"
      );
    }

    const session = loadSession();
    renderSession(session);
    showAuthMode("login");
    renderUploads([]);

    els.loginForm.addEventListener("submit", handleLogin);
    if (els.registerForm) els.registerForm.addEventListener("submit", handleRegister);
    els.logoutBtn.addEventListener("click", handleLogout);
    if (els.authTabLogin) {
      els.authTabLogin.addEventListener("click", () => {
        setError(els.loginError, "");
        showAuthMode("login");
      });
    }
    if (els.authTabRegister) {
      els.authTabRegister.addEventListener("click", () => {
        setError(els.registerError, "");
        showAuthMode("register");
      });
    }
    if (els.registerBackToLogin) {
      els.registerBackToLogin.addEventListener("click", () => showAuthMode("login"));
    }
    if (els.pendingRefreshBtn) {
      els.pendingRefreshBtn.addEventListener("click", () =>
        refreshPending(loadSession(), false)
      );
    }
    if (els.clearUploadsBtn) {
      els.clearUploadsBtn.addEventListener("click", () =>
        clearList("sources", loadSession(), els.clearUploadsBtn)
      );
    }
    if (els.clearResultsBtn) {
      els.clearResultsBtn.addEventListener("click", () =>
        clearList("results", loadSession(), els.clearResultsBtn)
      );
    }
    wireDropzone();

    if (session && apiConfigured()) {
      try {
        const me = await apiFetch("/auth/me", { method: "GET" }, session);
        const user = me.user || {};
        const username = user.username || me.username || session.username;
        const role = user.role || session.role || null;
        saveSession({ ...session, username, role });
        renderSession(loadSession());
        await refreshUploads(loadSession());
        if (isAdminSession(loadSession())) await refreshPending(loadSession());
      } catch (err) {
        if (err.status === 401 || err.status === 403) {
          saveSession(null);
          renderSession(null);
          showAuthMode("login");
        }
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
