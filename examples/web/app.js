(function () {
  "use strict";

  const CONFIRM_COMMANDS = [
    "report_confirm",
    "excel_confirm",
    "ppt_confirm",
    "dashboard_confirm",
  ];

  const DEFAULT_APPROVAL_ACTIONS = [
    { label: "Yes / Confirm", command: "report_confirm", userText: "已确认继续生成报告。" },
    { label: "No / Cancel", command: "cancel", userText: "已取消本次确认。" },
    { label: "Excel", command: "excel_confirm", userText: "已确认生成 Excel。" },
    { label: "PPT", command: "ppt_confirm", userText: "已确认生成 PPT。" },
    { label: "Dashboard", command: "dashboard_confirm", userText: "已确认生成 Dashboard。" },
    { label: "Report", command: "report_confirm", userText: "已确认生成 Report。" },
  ];

  const STREAM_EVENT_TYPES = [
    "node_start",
    "node_end",
    "tool_start",
    "tool_end",
    "text_delta",
    "chart_ref",
    "artifact_ref",
    "human_request",
    "usage",
    "llm_start",
    "llm_end",
    "llm_error",
    "llm_fallback",
    "llm_json_invalid",
    "done",
    "error",
    "stopped",
  ];

  const FIXED_LLM_MODE = "real_llm";
  const LLM_NODE_ALIASES = ["planner", "sql_drafter", "insight_writer"];
  const DEFAULT_LLM_ENABLED_NODES = ["planner", "sql_drafter", "insight_writer"];
  const CHART_ARTIFACT_MIME = "application/vnd.data-analysis-agent.chart+json";

  const OMITTED_PAYLOAD_KEYS = new Set([
    "chart_html",
    "html",
    "file_content",
    "file_bytes",
    "binary",
    "data_url",
    "content",
  ]);

  const state = {
    baseUrl: "http://127.0.0.1:8000",
    sessionId: "",
    sessions: [],
    currentSession: null,
    sessionStoreStatus: null,
    currentJobId: null,
    eventSource: null,
    lastFinalState: null,
    lastAnalysisPackage: null,
    lastReportOutline: null,
    routerDecision: null,
    contextSummary: null,
    datasources: [],
    currentDatasourceId: null,
    llmStatus: null,
    globalLlmConfig: null,
    artifacts: new Map(),
    errors: [],
    progressMessageId: null,
    timingRows: [],
    pendingHumanRequest: null,
    pendingApprovalKey: null,
    suppressHumanRequestJobId: null,
    apiReachable: true,
    isBusy: false,
    isSubmitting: false,
  };

  const $ = (id) => document.getElementById(id);

  document.addEventListener("DOMContentLoaded", () => {
    state.sessionId = "";
    $("session-id-input").value = "";
    $("top-session-id").textContent = "none";
    $("top-session-title").textContent = "暂无会话";
    bindEvents();
    showNoSessionState();
    refreshHealth();
    refreshDatasources();
    refreshLlmStatus();
    refreshSessions({ selectMostRecent: true });
  });

  function bindEvents() {
    $("base-url-input").addEventListener("change", () => {
      state.baseUrl = normalizeBaseUrl($("base-url-input").value);
      refreshHealth();
      refreshDatasources();
      refreshLlmStatus();
      refreshSessions();
    });
    $("session-id-input").addEventListener("change", () => {
      const nextSessionId = $("session-id-input").value.trim() || `web-${Date.now()}`;
      loadSession(nextSessionId, { createIfMissing: true });
    });
    $("new-session-btn").addEventListener("click", startNewSession);
    $("refresh-sessions-btn").addEventListener("click", refreshSessions);
    $("delete-session-btn").addEventListener("click", deleteCurrentSession);
    $("health-refresh-btn").addEventListener("click", refreshHealth);
    $("toggle-left-panel-btn").addEventListener("click", () => toggleSidebar("left"));
    $("toggle-right-panel-btn").addEventListener("click", () => toggleSidebar("right"));
    $("refresh-datasources-btn").addEventListener("click", refreshDatasources);
    $("set-session-datasource-btn").addEventListener("click", setCurrentDatasource);
    $("profile-datasource-btn").addEventListener("click", profileCurrentDatasource);
    $("register-datasource-btn").addEventListener("click", registerDatasource);
    $("register-file-path-btn").addEventListener("click", registerFilePathDatasource);
    $("upload-datasource-btn").addEventListener("click", uploadDatasourceFile);
    $("save-llm-config-btn").addEventListener("click", saveLlmConfig);
    $("save-global-llm-config-btn").addEventListener("click", saveGlobalLlmConfig);
    $("test-llm-config-btn").addEventListener("click", testLlmConfig);
    $("rename-session-btn").addEventListener("click", renameCurrentSession);
    $("datasource-select").addEventListener("change", () => {
      state.currentDatasourceId = $("datasource-select").value || null;
      updateDatasourceStatus();
    });
    $("send-btn").addEventListener("click", sendChat);
    $("cancel-job-btn").addEventListener("click", cancelCurrentJob);
    $("load-events-btn").addEventListener("click", loadEventList);
    $("close-preview-btn").addEventListener("click", closeActivePreview);
    $("message-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChat();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && closeActivePreviewOrDetails()) {
        event.preventDefault();
      }
    });
    document.querySelectorAll("[data-prompt]").forEach((button) => {
      button.addEventListener("click", () => {
        $("message-input").value = button.dataset.prompt || "";
        $("message-input").focus();
        if (button.dataset.command) {
          $("command-select").value = button.dataset.command;
        }
      });
    });
  }

  function toggleSidebar(side) {
    const className = side === "left" ? "left-panel-collapsed" : "right-panel-collapsed";
    document.body.classList.toggle(className);
  }

  function closeActivePreviewOrDetails() {
    if (closeActivePreview()) {
      return true;
    }
    const developerDetails = $("developer-details");
    if (developerDetails?.open) {
      developerDetails.open = false;
      return true;
    }
    return false;
  }

  function closeActivePreview() {
    const renderer = $("dashboard-renderer");
    const hasPreview = renderer && !renderer.classList.contains("empty");
    const hasRawPreview = $("artifact-preview")?.textContent?.trim() &&
      !$("artifact-preview").textContent.includes("点击 artifact");
    if (!hasPreview && !hasRawPreview) {
      return false;
    }
    clearDashboardRenderer();
    $("artifact-preview-kind").textContent = "metadata";
    $("artifact-preview").textContent = "点击 artifact 查看 metadata 或 JSON 预览";
    return true;
  }

  async function startNewSession() {
    closeEventSource();
    state.sessionId = `web-${Date.now()}`;
    state.currentJobId = null;
    state.currentSession = null;
    state.lastFinalState = null;
    state.lastAnalysisPackage = null;
    state.lastReportOutline = null;
    state.routerDecision = null;
    clearRouterDecision();
    state.currentDatasourceId = null;
    state.artifacts.clear();
    state.errors = [];
    state.pendingHumanRequest = null;
    state.pendingApprovalKey = null;
    state.suppressHumanRequestJobId = null;
    $("session-id-input").value = state.sessionId;
    $("top-session-id").textContent = state.sessionId;
    $("top-session-title").textContent = "新对话";
    $("top-current-datasource").textContent = "未选择数据源";
    $("datasource-select").value = "";
    $("current-job-id").textContent = "未创建";
    $("event-timeline").innerHTML = "";
    $("message-list").innerHTML = "";
    $("sql-output").textContent = "等待分析结果";
    $("sql-status").textContent = "empty";
    $("human-request-card").className = "human-card empty";
    $("human-request-card").textContent = "暂无待确认请求";
    $("human-status").textContent = "idle";
    renderApprovalShortcuts(null);
    renderArtifacts();
    clearDashboardRenderer();
    renderErrors();
    renderCurrentSessionSummary(null);
    updateComposerAvailability();
    appendMessage("assistant", "新会话已创建，可以继续提问。");
    await createSessionRecord(state.sessionId);
    await refreshSessions();
    await refreshSessionMessages();
    await refreshSessionJobs();
    refreshSessionDatasource();
    refreshSessionLlmStatus();
  }

  async function createSessionRecord(sessionId, title = null) {
    try {
      return await fetchJson("/sessions", {
        method: "POST",
        body: {
          session_id: sessionId,
          title,
        },
      });
    } catch (error) {
      pushError(`Create session failed: ${error.message}`);
      return null;
    }
  }

  async function refreshSessions(options = {}) {
    try {
      const sessions = await fetchJson("/sessions");
      state.sessions = Array.isArray(sessions) ? sessions : [];
      renderSessionList();
      const currentSession = state.sessions.find(
        (session) => session.session_id === state.sessionId,
      );
      if (currentSession) {
        state.currentSession = currentSession;
        renderCurrentSessionSummary(currentSession);
        return currentSession;
      }
      if (options.selectMostRecent && state.sessions.length) {
        const nextSession = mostRecentSession(state.sessions);
        if (nextSession) {
          await loadSession(nextSession.session_id);
          return nextSession;
        }
      }
      if (!state.sessions.length && !state.sessionId) {
        showNoSessionState();
      }
      return null;
    } catch (error) {
      state.sessions = [];
      renderSessionList();
      $("session-panel-status").textContent = `Session refresh failed: ${error.message}`;
      pushError(`Session refresh failed: ${error.message}`);
      return null;
    }
  }

  function mostRecentSession(sessions) {
    return [...sessions].sort((left, right) =>
      String(right.updated_at || "").localeCompare(String(left.updated_at || "")),
    )[0] || null;
  }

  function renderSessionList() {
    const list = $("session-list");
    if (!state.sessions.length) {
      list.innerHTML = '<div class="muted-note">暂无会话，请点击“新会话”开始。</div>';
      $("session-panel-status").textContent = "No saved sessions.";
      return;
    }
    list.innerHTML = "";
    state.sessions.forEach((session) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = `session-item${
        session.session_id === state.sessionId ? " active" : ""
      }`;
      item.innerHTML = `
        <span>${escapeHtml(session.title || "新对话")}</span>
        <small>${escapeHtml(session.last_message_preview || session.updated_at || "No messages yet")}</small>
        <small>${Number(session.message_count || 0)} message(s)</small>
      `;
      item.title = `session_id=${session.session_id}`;
      item.addEventListener("click", () => {
        loadSession(session.session_id);
      });
      list.appendChild(item);
    });
    $("session-panel-status").textContent = `${state.sessions.length} session(s)`;
  }

  async function loadSession(sessionId, options = {}) {
    closeEventSource();
    const session = await fetchSessionRecord(sessionId, options);
    if (!session) {
      return;
    }
    state.currentSession = session;
    state.contextSummary = session.context_summary || null;
    resetSessionView(session.session_id);
    state.currentSession = session;
    state.contextSummary = session.context_summary || null;
    renderCurrentSessionSummary(session);
    renderContextSummary(state.contextSummary);
    state.currentDatasourceId = session.datasource_id || null;
    $("datasource-select").value = state.currentDatasourceId || "";
    updateDatasourceStatus();
    collectArtifacts(session);
    renderArtifacts();
    await refreshSessionMessages();
    await refreshSessionJobs();
    await refreshSessionDatasource();
    await refreshSessionLlmStatus();
    await refreshSessions();
  }

  async function fetchSessionRecord(sessionId, options = {}) {
    try {
      return await fetchJson(`/sessions/${encodeURIComponent(sessionId)}`);
    } catch (error) {
      if (options.createIfMissing) {
        return createSessionRecord(sessionId);
      }
      pushError(`Load session failed: ${error.message}`);
      return null;
    }
  }

  function resetSessionView(sessionId) {
    state.sessionId = sessionId;
    state.currentJobId = null;
    state.lastFinalState = null;
    state.lastAnalysisPackage = null;
    state.lastReportOutline = null;
    state.routerDecision = null;
    state.contextSummary = null;
    clearRouterDecision();
    renderContextSummary(null);
    state.artifacts.clear();
    state.errors = [];
    state.pendingHumanRequest = null;
    state.pendingApprovalKey = null;
    state.suppressHumanRequestJobId = null;
    $("session-id-input").value = state.sessionId;
    $("top-session-id").textContent = state.sessionId;
    $("current-job-id").textContent = "未创建";
    $("event-timeline").innerHTML = "";
    $("message-list").innerHTML = "";
    $("sql-output").textContent = "等待分析结果";
    $("sql-status").textContent = "empty";
    $("human-request-card").className = "human-card empty";
    $("human-request-card").textContent = "暂无待确认请求";
    $("human-status").textContent = "idle";
    renderApprovalShortcuts(null);
    renderArtifacts();
    clearDashboardRenderer();
    renderErrors();
    updateComposerAvailability();
  }


  function showNoSessionState() {
    closeEventSource();
    state.sessionId = "";
    state.currentSession = null;
    state.currentJobId = null;
    state.lastFinalState = null;
    state.lastAnalysisPackage = null;
    state.lastReportOutline = null;
    state.routerDecision = null;
    clearRouterDecision();
    state.artifacts.clear();
    state.errors = [];
    state.pendingHumanRequest = null;
    state.pendingApprovalKey = null;
    state.suppressHumanRequestJobId = null;
    $("session-id-input").value = "";
    $("session-title-input").value = "";
    $("top-session-id").textContent = "none";
    $("top-session-title").textContent = "暂无会话";
    $("current-job-id").textContent = "新对话";
    $("event-timeline").innerHTML = "";
    $("message-list").innerHTML = "";
    appendMessage("assistant", "暂无会话，请新建会话开始分析。");
    $("message-input").value = "";
    updateComposerAvailability();
    $("sql-output").textContent = "未选择数据源";
    $("sql-status").textContent = "empty";
    $("human-request-card").className = "human-card empty";
    $("human-request-card").textContent = "暂无待确认请求";
    $("human-status").textContent = "idle";
    renderApprovalShortcuts(null);
    renderArtifacts();
    clearDashboardRenderer();
    renderErrors();
    renderCurrentSessionSummary(null);
    setBusy(false, "No session");
  }

  async function deleteCurrentSession() {
    if (!state.sessionId) {
      showNoSessionState();
      return;
    }
    const title = state.currentSession?.title || state.sessionId;
    const confirmed = window.confirm(
      `Delete session "${title}"? This removes visible chat history and cannot be undone.`,
    );
    if (!confirmed) {
      return;
    }
    const deletedSessionId = state.sessionId;
    try {
      await fetchJson(`/sessions/${encodeURIComponent(deletedSessionId)}`, {
        method: "DELETE",
      });
      state.sessions = state.sessions.filter((session) => session.session_id !== deletedSessionId);
      renderSessionList();
      const nextSession = mostRecentSession(state.sessions);
      if (nextSession) {
        await loadSession(nextSession.session_id);
        return;
      }
      showNoSessionState();
      await refreshSessions();
    } catch (error) {
      pushError(`Delete session failed: ${error.message}`);
    }
  }

  async function refreshSessionMessages() {
    try {
      const messages = await fetchJson(
        `/sessions/${encodeURIComponent(state.sessionId)}/messages`,
      );
      renderSessionMessages(Array.isArray(messages) ? messages : []);
    } catch (error) {
      pushError(`Load session messages failed: ${error.message}`);
    }
  }

  function renderSessionMessages(messages) {
    $("message-list").innerHTML = "";
    state.artifacts.clear();
    collectArtifacts(state.currentSession);
    if (!messages.length) {
      appendMessage(
        "assistant",
        "\u6b22\u8fce\u4f7f\u7528\u6570\u636e\u5206\u6790\u5de5\u4f5c\u53f0\u3002\u8bf7\u5148\u9009\u62e9\u6216\u6ce8\u518c\u6570\u636e\u6e90\uff0c\u7136\u540e\u53ef\u4ee5\u70b9\u51fb\u793a\u4f8b\u95ee\u9898\u5f00\u59cb\u3002\u5f53\u524d\u9ed8\u8ba4\u4f7f\u7528\u89c4\u5219\u6a21\u5f0f\uff1b\u5982\u9700\u6a21\u578b\u53c2\u4e0e\uff0c\u53ef\u5728\u5f00\u53d1\u8005\u8be6\u60c5\u4e2d\u542f\u7528 LLM \u8282\u70b9\u3002",
      );
      renderArtifacts();
      return;
    }
    messages.forEach((message) => {
      appendMessage(message.role === "user" ? "user" : "assistant", message.content);
      collectArtifacts(message);
    });
    renderArtifacts();
  }

  async function refreshSessionJobs() {
    try {
      const jobs = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/jobs`);
      renderSessionJobs(Array.isArray(jobs) ? jobs : []);
    } catch (error) {
      $("session-job-list").innerHTML = "";
      pushError(`Load session jobs failed: ${error.message}`);
    }
  }

  function renderSessionJobs(jobs) {
    const list = $("session-job-list");
    if (!jobs.length) {
      list.innerHTML = '<div class="muted-note">No jobs yet.</div>';
      return;
    }
    list.innerHTML = "";
    jobs.slice(0, 5).forEach((job) => {
      const item = document.createElement("div");
      item.className = "session-job-item";
      item.textContent = `${job.status} / ${job.intent} / ${job.command}`;
      list.appendChild(item);
    });
  }

  function renderSessionStoreStatus(status) {
    const storeType = status?.store_type || "memory";
    state.sessionStoreStatus = status || null;
    $("top-session-store").textContent = storeType;
    $("session-store-type").textContent = storeType;
    $("session-store-warning").textContent =
      storeType === "memory"
        ? "Memory history is temporary and disappears after API restart."
        : `Persistent history enabled${status?.db_url_masked ? `: ${status.db_url_masked}` : "."}`;
  }

  function renderCurrentSessionSummary(session) {
    if (!session) {
      if (!state.sessionId) {
        $("top-session-title").textContent = "暂无会话";
        $("top-session-id").textContent = "none";
        $("session-title-input").value = "";
      }
      $("current-session-message-count").textContent = "0";
      $("current-session-updated-at").textContent = "unknown";
      return;
    }
    const title = session.title || "新对话";
    $("top-session-title").textContent = title;
    $("top-session-id").textContent = state.sessionId || "pending";
    $("session-title-input").value = title;
    $("current-session-message-count").textContent = String(session.message_count || 0);
    $("current-session-updated-at").textContent = session.updated_at || "unknown";
  }

  async function renameCurrentSession() {
    const title = $("session-title-input").value.trim();
    if (!title) {
      pushWarning("Session title cannot be empty.");
      return;
    }
    try {
      const session = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}`, {
        method: "PATCH",
        body: { title },
      });
      state.currentSession = session;
      renderCurrentSessionSummary(session);
      await refreshSessions();
    } catch (error) {
      pushError(`Rename session failed: ${error.message}`);
    }
  }

  async function refreshHealth() {
    state.baseUrl = normalizeBaseUrl($("base-url-input").value);
    $("api-health").textContent = "checking";
    $("runtime-health").textContent = "checking";
    try {
      const health = await fetchJson("/health");
      const runtime = await fetchJson("/health/runtime");
      $("api-health").textContent = health.status || "unknown";
      $("runtime-health").textContent = runtime.status || "unknown";
      $("runner-backend").textContent = runtime.runner_backend || health.runner_backend || "unknown";
      $("top-runner-backend").textContent =
        runtime.runner_backend || health.runner_backend || "unknown";
      $("top-datasource-status").textContent = datasourceStatusLabel(runtime);
      $("top-llm-mode").textContent = llmModeLabel(runtime);
      $("optional-status").textContent = optionalRuntimeLabel(runtime);
      renderSessionStoreStatus(runtime.session_store || { store_type: "memory" });
      updateFileDatasourceRuntimeHints(runtime);
      state.apiReachable = true;
      updateDatasourceStatus();
      updateComposerAvailability();
    } catch (error) {
      state.apiReachable = false;
      updateComposerAvailability();
      $("api-health").textContent = "unreachable";
      $("runtime-health").textContent = "unreachable";
      $("top-runner-backend").textContent = "unreachable";
      $("top-datasource-status").textContent = "unknown";
      $("top-current-datasource").textContent = "未选择数据源";
      $("top-llm-mode").textContent = "rule";
      renderSessionStoreStatus({ store_type: "unknown" });
      updateFileDatasourceRuntimeHints(null);
      pushError(`Health check failed: ${error.message}`);
    }
  }

  function updateFileDatasourceRuntimeHints(runtime) {
    const maxUploadLabel = runtime?.max_upload_mb
      ? `${runtime.max_upload_mb} MB`
      : "the API runtime setting";
    const localPathEnabled = runtime?.local_file_paths_enabled === true;
    const pathNote = $("file-path-mode-note");
    const uploadNote = $("upload-format-note");
    if (pathNote) {
      pathNote.textContent = localPathEnabled
        ? "Local file path mode is enabled for this API. Only CSV, Excel, and optional Parquet files are accepted; sensitive paths and path traversal are rejected."
        : "Local file paths are disabled. Ask the API operator to set DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true for local development, or use file upload.";
    }
    if (uploadNote) {
      uploadNote.textContent =
        `Supported formats: CSV and Excel xlsx. Parquet is optional and requires pyarrow. Maximum upload size: ${maxUploadLabel}.`;
    }
  }

  async function refreshDatasources() {
    try {
      const datasources = await fetchJson("/datasources");
      state.datasources = Array.isArray(datasources) ? datasources : [];
      renderDatasourceOptions();
      await refreshSessionDatasource();
      updateDatasourceStatus();
    } catch (error) {
      state.datasources = [];
      renderDatasourceOptions();
      $("datasource-panel-status").textContent = `Datasource refresh failed: ${error.message}`;
      $("top-datasource-status").textContent = "unreachable";
      pushError(`Datasource refresh failed: ${error.message}`);
    }
  }

  async function refreshLlmStatus() {
    try {
      await refreshGlobalLlmConfig();
      const status = await fetchJson("/llm/status");
      state.llmStatus = status;
      renderLlmStatus(status);
      await refreshSessionLlmStatus();
    } catch (error) {
      $("llm-status-panel").textContent = `LLM status unavailable: ${error.message}`;
      $("top-llm-mode").textContent = "unknown";
      $("top-llm-provider-model").textContent = "unknown";
      $("top-llm-enabled-nodes").textContent = "none";
      $("top-llm-api-key").textContent = "unknown";
    }
  }

  async function refreshGlobalLlmConfig() {
    try {
      const config = await fetchJson("/llm/config");
      state.globalLlmConfig = config;
      renderGlobalLlmConfig(config);
    } catch (error) {
      $("llm-config-status-panel").textContent = `Provider config unavailable: ${error.message}`;
    }
  }

  function renderGlobalLlmConfig(config) {
    const provider = config?.provider || "openai_compatible";
    $("llm-provider-select").value = provider;
    $("llm-model-input").value = config?.model || "";
    $("llm-base-url-input").value = config?.base_url_masked || "";
    $("llm-api-key-input").value = "";
    $("llm-api-key-input").placeholder = config?.api_key_configured
      ? "已配置；留空可保留现有 key"
      : "粘贴 API key 后保存";
    $("llm-config-status-panel").textContent = config?.api_key_configured
      ? `Provider config saved; API key configured. Provider=${provider}.`
      : `Provider config saved; API key missing. Provider=${provider}.`;
    const configuredNodes = filterSupportedLlmNodes(config?.enabled_nodes);
    const recommendedNodes = configuredNodes.length
      ? configuredNodes
      : DEFAULT_LLM_ENABLED_NODES;
    document.querySelectorAll("[data-llm-node]").forEach((input) => {
      input.checked = recommendedNodes.includes(input.value);
    });
  }

  function llmConfigPayload() {
    const apiKey = $("llm-api-key-input").value.trim();
    const payload = {
      provider: $("llm-provider-select").value || "openai_compatible",
      model: $("llm-model-input").value.trim(),
      base_url: $("llm-base-url-input").value.trim() || null,
      enabled_nodes: selectedLlmNodes(),
    };
    if (apiKey) {
      payload.api_key = apiKey;
    }
    return payload;
  }

  async function saveGlobalLlmConfig(options = {}) {
    const { refreshStatus = true, quiet = false } = options;
    try {
      const config = await fetchJson("/llm/config", {
        method: "POST",
        body: llmConfigPayload(),
      });
      state.globalLlmConfig = config;
      renderGlobalLlmConfig(config);
      if (refreshStatus) {
        await refreshLlmStatus();
      }
      return config;
    } catch (error) {
      const message = humanizeLlmConfigError(error.message);
      $("llm-config-status-panel").textContent = `Provider config save failed: ${message}`;
      if (!quiet) {
        pushError(`Provider config save failed: ${message}`);
      }
      throw new Error(message);
    }
  }

  async function testLlmConfig() {
    try {
      const result = await fetchJson("/llm/test", {
        method: "POST",
        body: llmConfigPayload(),
      });
      $("llm-config-status-panel").textContent = result.ok
        ? `Connection test passed: ${result.message}`
        : `Connection test failed: ${result.message}`;
      if (!result.ok) {
        pushWarning(`LLM test failed: ${result.message}`);
      }
    } catch (error) {
      $("llm-config-status-panel").textContent = `Connection test failed: ${error.message}`;
      pushError(`Connection test failed: ${error.message}`);
    }
  }

  async function refreshSessionLlmStatus() {
    if (!state.sessionId) {
      return;
    }
    try {
      const status = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/llm`);
      state.llmStatus = status;
      renderLlmStatus(status);
    } catch (error) {
      $("llm-status-panel").textContent = `Session LLM status unavailable: ${error.message}`;
    }
  }

  async function saveLlmConfig() {
    if (!state.sessionId) {
      pushError("Create a session before saving session LLM settings.");
      return;
    }
    const enabledNodes = selectedLlmNodes();
    try {
      await saveGlobalLlmConfig({ refreshStatus: false, quiet: true });
      const status = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/llm`, {
        method: "POST",
        body: {
          mode: FIXED_LLM_MODE,
          enabled_nodes: enabledNodes,
        },
      });
      state.llmStatus = status;
      renderLlmStatus(status);
      $("llm-status-panel").textContent = `Saved ${status.mode} for this session.`;
      $("llm-config-status-panel").textContent =
        "Provider config saved; session LLM settings saved. API key will not be shown.";
      await refreshLlmStatus();
      await refreshSessionLlmStatus();
      refreshSessions();
    } catch (error) {
      const message = humanizeLlmConfigError(error.message);
      $("llm-status-panel").textContent = `LLM config save failed: ${message}`;
      pushError(`LLM config save failed: ${message}`);
    }
  }

  function selectedLlmNodes() {
    const selectedNodes = Array.from(document.querySelectorAll("[data-llm-node]:checked")).map(
      (input) => input.value,
    );
    const filteredNodes = filterSupportedLlmNodes(selectedNodes);
    return filteredNodes.length ? filteredNodes : DEFAULT_LLM_ENABLED_NODES;
  }

  function filterSupportedLlmNodes(nodes) {
    if (!Array.isArray(nodes)) {
      return [];
    }
    return nodes.filter((nodeName) => LLM_NODE_ALIASES.includes(nodeName));
  }

  function renderLlmStatus(status) {
    const enabledNodes = filterSupportedLlmNodes(status.enabled_nodes);
    const providerModel = [status.provider, status.model].filter(Boolean).join("/") || "none";
    $("top-llm-mode").textContent = humanLlmMode(status.mode);
    $("top-llm-provider-model").textContent = providerModel;
    $("top-llm-enabled-nodes").textContent = enabledNodes.length
      ? enabledNodes.join(",")
      : "none";
    $("top-llm-api-key").textContent = status.api_key_configured ? "configured" : "missing";
    $("llm-mode-select").value = FIXED_LLM_MODE;
    $("llm-mode-fixed-label").textContent = FIXED_LLM_MODE;
    const checkboxNodes = enabledNodes.length
      ? enabledNodes
      : filterSupportedLlmNodes(state.globalLlmConfig?.enabled_nodes).length
        ? filterSupportedLlmNodes(state.globalLlmConfig?.enabled_nodes)
        : DEFAULT_LLM_ENABLED_NODES;
    document.querySelectorAll("[data-llm-node]").forEach((input) => {
      input.checked = checkboxNodes.includes(input.value);
    });
    $("llm-mode-badge").textContent = humanLlmMode(status.mode);
    $("llm-call-count").textContent = String(status.last_llm_call_count || 0);
    $("llm-error-count").textContent = String(status.last_llm_error_count || 0);
    $("llm-fallback-count").textContent = String(status.last_llm_fallback_count || 0);
    $("llm-json-invalid-count").textContent = String(status.last_llm_json_invalid_count || 0);
    $("llm-status-panel").textContent =
      `provider=${providerModel}; base=${status.base_url_host || "none"}; api_key=${
        status.api_key_configured ? "configured" : "missing"
      }`;
  }

  function humanLlmMode(mode) {
    if (mode === "real_llm") {
      return "real LLM";
    }
    if (mode === "rule") {
      return "rule mode";
    }
    return "LLM inactive";
  }

  function humanizeLlmConfigError(message) {
    const text = String(message || "LLM config error");
    const missingLabels = {
      missing_provider: "provider 缺失",
      missing_model: "model 缺失",
      missing_api_key: "API key 未配置",
      missing_base_url: "base_url 缺失",
    };
    const matched = Object.entries(missingLabels)
      .filter(([field]) => text.includes(field))
      .map(([, label]) => label);
    if (matched.length) {
      return `LLM provider 配置不完整：${matched.join("、")}。`;
    }
    if (text.includes("Failed to fetch") || text.includes("NetworkError")) {
      return friendlyNetworkError({ message: text });
    }
    return text;
  }

  function recordLlmEventInUi(eventType) {
    const counterByEvent = {
      llm_start: "llm-call-count",
      llm_error: "llm-error-count",
      llm_fallback: "llm-fallback-count",
      llm_json_invalid: "llm-json-invalid-count",
    };
    const counterId = counterByEvent[eventType];
    if (!counterId) {
      return;
    }
    const current = Number.parseInt($(counterId).textContent || "0", 10);
    $(counterId).textContent = String(Number.isFinite(current) ? current + 1 : 1);
  }

  async function refreshSessionDatasource() {
    if (!state.sessionId) {
      state.currentDatasourceId = null;
      updateDatasourceStatus();
      return;
    }
    try {
      const result = await fetchJson(
        `/sessions/${encodeURIComponent(state.sessionId)}/datasource`,
      );
      state.currentDatasourceId = result.datasource_id || null;
      if (state.currentDatasourceId) {
        $("datasource-select").value = state.currentDatasourceId;
      }
      updateDatasourceStatus();
    } catch (error) {
      state.currentDatasourceId = null;
      updateDatasourceStatus();
    }
  }

  async function registerDatasource() {
    const datasourceId = $("register-datasource-id-input").value.trim();
    const name = $("register-datasource-name-input").value.trim();
    const kind = $("register-datasource-kind-select").value;
    const sourceValue = $("register-datasource-url-input").value.trim();
    if (!datasourceId || !sourceValue) {
      pushError("Datasource ID and path/URL are required.");
      return;
    }
    const payload = {
      datasource_id: datasourceId,
      name: name || datasourceId,
      kind,
    };
    if (kind === "sqlite") {
      payload.db_path = sourceValue;
    } else {
      payload.url = sourceValue;
    }
    try {
      const record = await fetchJson("/datasources", { method: "POST", body: payload });
      state.currentDatasourceId = record.datasource_id;
      await refreshDatasources();
      await setCurrentDatasource();
      $("datasource-panel-status").textContent = `Registered ${record.datasource_id}`;
    } catch (error) {
      pushError(`Register datasource failed: ${error.message}`);
      $("datasource-panel-status").textContent = "Register failed";
    }
  }

  async function registerFilePathDatasource() {
    const datasourceId = $("file-path-datasource-id-input").value.trim();
    const name = $("file-path-name-input").value.trim();
    const tableName = $("file-path-table-input").value.trim();
    const path = $("file-path-input").value.trim();
    if (!path) {
      pushError("Local file path is required.");
      return;
    }
    const payload = { path };
    if (datasourceId) {
      payload.datasource_id = datasourceId;
    }
    if (name) {
      payload.name = name;
    }
    if (tableName) {
      payload.table_name = tableName;
    }
    try {
      const record = await fetchJson("/datasources/from-path", {
        method: "POST",
        body: payload,
      });
      await acceptDatasourceRecord(
        record,
        `Registered ${record.datasource_id}. Next: select datasource, profile, then ask a question.`
      );
    } catch (error) {
      const friendlyMessage = friendlyDatasourceError(error.message);
      pushError(`Register file path failed: ${friendlyMessage}`);
      $("datasource-panel-status").textContent = friendlyMessage;
    }
  }

  async function uploadDatasourceFile() {
    const input = $("datasource-upload-input");
    const selectedFile = input.files?.[0];
    if (!selectedFile) {
      pushError("Choose a CSV, Excel or Parquet file first.");
      return;
    }
    const formData = new FormData();
    formData.append("file", selectedFile);
    const datasourceId = $("upload-datasource-id-input").value.trim();
    const name = $("upload-name-input").value.trim();
    const tableName = $("upload-table-input").value.trim();
    if (datasourceId) {
      formData.append("datasource_id", datasourceId);
    }
    if (name) {
      formData.append("name", name);
    }
    if (tableName) {
      formData.append("table_name", tableName);
    }
    try {
      const record = await fetchFormData("/datasources/upload", formData);
      await acceptDatasourceRecord(
        record,
        `Uploaded ${record.datasource_id}. Next: select datasource, profile, then ask a question.`
      );
      input.value = "";
    } catch (error) {
      const friendlyMessage = friendlyDatasourceError(error.message);
      pushError(`Upload datasource failed: ${friendlyMessage}`);
      $("datasource-panel-status").textContent = friendlyMessage;
    }
  }

  async function acceptDatasourceRecord(record, statusText) {
    state.currentDatasourceId = record.datasource_id;
    await refreshDatasources();
    await setCurrentDatasource();
    $("datasource-panel-status").textContent = statusText;
  }

  function friendlyDatasourceError(message) {
    const text = String(message || "Datasource operation failed.");
    const lower = text.toLowerCase();
    if (lower.includes("exceeds limit") || lower.includes("file exceeds upload limit")) {
      return text;
    }
    if (lower.includes("unsupported file datasource")) {
      return "Unsupported file type. Use CSV, Excel xlsx, or Parquet when the optional dependency is installed.";
    }
    if (lower.includes("empty") || lower.includes("missing a header")) {
      return "The file is empty or missing a header row.";
    }
    if (lower.includes("failed to parse")) {
      return "The file could not be parsed. Check the file format and header row.";
    }
    if (lower.includes("pyarrow") || lower.includes("parquet")) {
      return "Parquet requires the optional pyarrow dependency. Use CSV/Excel or install pyarrow.";
    }
    if (lower.includes("disabled") && lower.includes("local file path")) {
      return "Local file path registration is disabled. Use upload or enable DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS for local development.";
    }
    if (lower.includes("path traversal") || lower.includes("path separators")) {
      return "Path traversal is not allowed. Use a normal filename or safe local path.";
    }
    if (lower.includes("sensitive")) {
      return "Sensitive paths and environment files cannot be used as datasources.";
    }
    return text;
  }

  async function setCurrentDatasource() {
    if (!state.sessionId) {
      pushError("Create a session before selecting a datasource for analysis.");
      return;
    }
    const datasourceId = $("datasource-select").value || state.currentDatasourceId;
    if (!datasourceId) {
      pushError("Select a datasource first.");
      return;
    }
    try {
      const result = await fetchJson(
        `/sessions/${encodeURIComponent(state.sessionId)}/datasource`,
        {
          method: "POST",
          body: { datasource_id: datasourceId },
        },
      );
      state.currentDatasourceId = result.datasource_id || datasourceId;
      $("datasource-select").value = state.currentDatasourceId;
      updateDatasourceStatus();
      $("datasource-panel-status").textContent = `Session uses ${state.currentDatasourceId}`;
      refreshSessions();
    } catch (error) {
      pushError(`Set datasource failed: ${error.message}`);
    }
  }

  async function profileCurrentDatasource() {
    const datasourceId = $("datasource-select").value || state.currentDatasourceId;
    if (!datasourceId) {
      pushError("Select a datasource before profiling.");
      return;
    }
    setBusy(true, `Profiling ${datasourceId}`);
    try {
      await setCurrentDatasource();
      const job = await fetchJson(`/datasources/${encodeURIComponent(datasourceId)}/profile`, {
        method: "POST",
      });
      $("datasource-panel-status").textContent = `Profile job ${job.job_id}`;
      handleJobCreated(job);
    } catch (error) {
      setBusy(false, "Profile failed");
      pushError(`Profile datasource failed: ${error.message}`);
    }
  }

  function renderDatasourceOptions() {
    const select = $("datasource-select");
    select.innerHTML = '<option value="">No datasource selected</option>';
    state.datasources.forEach((record) => {
      const option = document.createElement("option");
      option.value = record.datasource_id;
      option.textContent = `${record.name || record.datasource_id} (${record.kind})`;
      select.appendChild(option);
    });
    if (state.currentDatasourceId) {
      select.value = state.currentDatasourceId;
    }
    renderDatasourceList();
  }

  function renderDatasourceList() {
    const list = $("datasource-list");
    $("datasource-count-badge").textContent = String(state.datasources.length);
    if (!state.datasources.length) {
      list.innerHTML = '<div class="muted-note">No datasource registered.</div>';
      $("datasource-panel-status").textContent =
        "No datasource registered. Connect SQL, register a file path, or upload CSV/Excel.";
      return;
    }
    list.innerHTML = "";
    state.datasources.forEach((record) => {
      const item = document.createElement("article");
      item.className = "datasource-item";
      item.innerHTML = `
        <div class="datasource-title">
          <span>${escapeHtml(record.datasource_id)}</span>
          <span>${escapeHtml(record.status || "available")}</span>
        </div>
        <div class="datasource-meta">
          ${escapeHtml(record.name || "")}
          ${record.schema_hash ? ` · schema ${escapeHtml(record.schema_hash.slice(0, 8))}` : ""}
        </div>
      `;
      const metadata = [
        record.name || "",
        record.original_filename || "",
        record.table_name ? `table ${record.table_name}` : "",
        Number.isInteger(record.row_count) ? `rows ${record.row_count}` : "",
        record.schema_hash ? `schema ${record.schema_hash.slice(0, 8)}` : "",
      ].filter(Boolean);
      const meta = item.querySelector(".datasource-meta");
      if (meta) {
        meta.textContent = metadata.join(" | ");
      }
      list.appendChild(item);
    });
  }

  function updateDatasourceStatus() {
    const current = state.currentDatasourceId || $("datasource-select")?.value || "";
    $("top-current-datasource").textContent = current || "未选择数据源";
    $("datasource-panel-status").textContent = current
      ? `Current datasource: ${current}`
      : "No datasource selected.";
  }

  async function sendChat() {
    if (!state.sessionId) {
      appendMessage("assistant", "暂无会话，请点击新会话开始分析。");
      return;
    }
    if ($("send-btn").disabled) {
      setBusy(true, "Job already running");
      pushWarning("A job is already running. Cancel it or wait for completion before sending again.");
      return;
    }
    const message = $("message-input").value.trim();
    if (!message) {
      return;
    }

    const command = $("command-select").value || "none";
    appendMessage("user", command === "none" ? message : `/${command} ${message}`);
    $("message-input").value = "";

    const datasourceId = state.currentDatasourceId || $("datasource-select").value;
    if (!datasourceId && requiresDatasource(message, command)) {
      appendMessage(
        "assistant",
        state.datasources.length
          ? "请先在左侧选择一个数据源，然后再开始分析。"
          : "还没有可用数据源。请先在左侧连接 SQL、注册文件路径或上传 CSV/Excel。",
      );
      setBusy(false, "Ready");
      return;
    }

    state.isSubmitting = true;
    setBusy(true, "Submitting job");

    const payload = {
      message,
      command,
    };
    if (datasourceId) {
      payload.datasource_id = datasourceId;
    }
    if (command === "report" && state.lastAnalysisPackage) {
      payload.analysis_package = state.lastAnalysisPackage;
    }
    if (command === "report" && state.lastReportOutline) {
      payload.report_outline = state.lastReportOutline;
    }

    try {
      const job = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/chat`, {
        method: "POST",
        body: payload,
      });
      state.isSubmitting = false;
      handleJobCreated(job);
    } catch (error) {
      state.isSubmitting = false;
      setBusy(false, "Submit failed");
      appendMessage("assistant", error.message, { error: true });
      pushError(error.message);
    }
  }

  function requiresDatasource(message, command) {
    if (["analyze", "explore", "profile", "report"].includes(command)) {
      return true;
    }
    return /销售|gmv|订单|数据库|分析|趋势|top|地区|品类|报表|报告/i.test(message);
  }

  function handleJobCreated(job) {
    state.isSubmitting = false;
    state.currentJobId = job.job_id;
    state.timingRows = [];
    clearProgressDelta();
    renderTimingPanel();
    $("current-job-id").textContent = job.job_id;
    $("cancel-job-btn").disabled = false;
    $("load-events-btn").disabled = false;
    setBusy(true, `Job ${job.status || "running"}`);
    subscribeToEvents(job.job_id);
  }

  function subscribeToEvents(jobId) {
    closeEventSource();
    const url = `${state.baseUrl}/jobs/${encodeURIComponent(jobId)}/events/stream`;
    const source = new EventSource(url);
    state.eventSource = source;
    setBusy(true, "Listening to SSE");

    STREAM_EVENT_TYPES.forEach((eventType) => {
      source.addEventListener(eventType, (event) => {
        if (eventType === "error" && !event.data) {
          return;
        }
        const data = parseEventData(event.data);
        handleAgentEvent(eventType, data);
        if (["done", "error", "stopped"].includes(eventType)) {
          closeEventSource();
          refreshFinalJob(jobId);
        }
      });
    });
    source.onmessage = (event) => {
      handleAgentEvent("message", parseEventData(event.data));
    };
    source.onerror = () => {
      closeEventSource();
      setBusy(false, "SSE closed");
      refreshFinalJob(jobId);
    };
  }

  function handleAgentEvent(eventType, eventData) {
    const normalizedType = eventData.event_type || eventType;
    const safeEvent = sanitizeEventPayload(eventData);
    addTimelineRow(normalizedType, safeEvent);
    collectTiming(normalizedType, safeEvent);
    recordLlmEventInUi(normalizedType);
    renderRouterDecision(safeEvent.payload?.router_decision || safeEvent.router_decision);
    collectArtifacts(safeEvent);
    if (normalizedType === "node_start") {
      setBusy(true, `Running ${safeEvent.node_name || "node"}`);
    }
    if (normalizedType === "node_end") {
      setBusy(true, `Completed ${safeEvent.node_name || "node"}`);
    }
    if (normalizedType === "text_delta" && safeEvent.message) {
      setBusy(false, safeEvent.message);
      renderProgressDelta(safeEvent.message);
    }
    if (
      normalizedType === "human_request" &&
      state.suppressHumanRequestJobId !== state.currentJobId
    ) {
      renderHumanRequest(safeEvent.payload || safeEvent);
    }
    if (normalizedType === "error" || normalizedType === "llm_error") {
      setBusy(false, "Job error");
      pushError(eventSummary(safeEvent));
    }
    if (normalizedType === "done" || normalizedType === "stopped") {
      setBusy(false, `Job ${normalizedType}`);
      clearProgressDelta();
    }
    if (normalizedType === "llm_fallback" || normalizedType === "llm_json_invalid") {
      pushWarning(eventSummary(safeEvent));
    }
    if (normalizedType === "chart_ref" || normalizedType === "artifact_ref") {
      renderArtifacts();
    }
  }

  async function refreshFinalJob(jobId) {
    try {
      const job = await fetchJson(`/jobs/${encodeURIComponent(jobId)}`);
      state.lastFinalState = job.final_state || null;
      if (state.lastFinalState) {
        state.lastAnalysisPackage = state.lastFinalState.analysis_package || state.lastAnalysisPackage;
        state.lastReportOutline = state.lastFinalState.report_outline || state.lastReportOutline;
        renderRouterDecision(state.lastFinalState.router_decision);
        state.contextSummary = state.lastFinalState.context_summary || state.contextSummary;
        renderContextSummary(state.contextSummary);
        renderSql(state.lastFinalState);
        collectTimingFromFinalState(state.lastFinalState);
        renderTimingPanel();
        collectArtifacts(state.lastFinalState);
        renderArtifacts();
        if (
          state.lastFinalState.human_request &&
          state.suppressHumanRequestJobId !== job.job_id
        ) {
          renderHumanRequest(state.lastFinalState.human_request);
        }
      }
      if (job.final_response_text) {
        clearProgressDelta();
        if (state.lastFinalState?.schema_qa_result) {
          appendSchemaQaMessage(state.lastFinalState.schema_qa_result, job.final_response_text);
        } else {
          appendMessage("assistant", job.final_response_text);
        }
      }
      if (job.error_message) {
        pushError(job.error_message);
      }
      setBusy(false, `Job ${job.status}`);
      refreshSessionMessages();
      refreshSessionJobs();
      refreshSessions();
      refreshSessionLlmStatus();
    } catch (error) {
      pushError(`Failed to refresh job: ${error.message}`);
    }
  }

  async function loadEventList() {
    if (!state.currentJobId) {
      return;
    }
    try {
      const events = await fetchJson(`/jobs/${encodeURIComponent(state.currentJobId)}/events`);
      $("event-timeline").innerHTML = "";
      events.forEach((event) => handleAgentEvent(event.event_type || "message", event));
    } catch (error) {
      pushError(`Failed to load events: ${error.message}`);
    }
  }

  async function cancelCurrentJob() {
    if (!state.currentJobId) {
      return;
    }
    try {
      const job = await fetchJson(`/jobs/${encodeURIComponent(state.currentJobId)}/cancel`, {
        method: "POST",
      });
      setBusy(false, `Job ${job.status}`);
      await loadEventList();
      await refreshSessionMessages();
      await refreshSessionJobs();
      await refreshSessions();
    } catch (error) {
      pushError(`Cancel failed: ${error.message}`);
    }
  }

  async function approveCurrentJob(command, userText = null) {
    if (!state.currentJobId) {
      return;
    }
    if (command === "cancel") {
      appendAndPersistUserChoice(userText || "已取消本次确认。");
      state.suppressHumanRequestJobId = state.currentJobId;
      clearPendingApproval("已取消。");
      await cancelCurrentJob();
      return;
    }
    setBusy(true, `Approving ${command}`);
    try {
      appendAndPersistUserChoice(userText || approvalUserText(command));
      const job = await fetchJson(`/jobs/${encodeURIComponent(state.currentJobId)}/approve`, {
        method: "POST",
        body: { command },
      });
      state.currentJobId = job.job_id;
      state.suppressHumanRequestJobId = job.job_id;
      $("current-job-id").textContent = job.job_id;
      clearPendingApproval(`已发送 ${command}，等待导出结果。`);
      subscribeToEvents(job.job_id);
    } catch (error) {
      setBusy(false, "Approve failed");
      pushError(`Approve failed: ${error.message}`);
    }
  }

  function appendAndPersistUserChoice(text) {
    appendMessage("user", text);
    persistSessionMessage("user", text, { source: "inline_approval" });
  }

  async function persistSessionMessage(role, content, metadata = {}) {
    try {
      await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/messages`, {
        method: "POST",
        body: {
          role,
          content,
          metadata,
        },
      });
    } catch (error) {
      pushWarning(`Message history write failed: ${error.message}`);
    }
  }

  function renderHumanRequest(humanRequest) {
    state.pendingHumanRequest = humanRequest;
    state.pendingApprovalKey = approvalKey(humanRequest);
    const card = $("human-request-card");
    $("human-status").textContent = "waiting";
    $("inline-approval-panel").classList.remove("empty");
    $("inline-approval-panel").classList.add("attention-pulse");
    card.className = "human-card";
    card.innerHTML = "";
    buildApprovalCard(card, humanRequest, { compact: false });
    renderApprovalShortcuts(humanRequest);
    upsertApprovalMessage(humanRequest);
    const firstButton = $("approval-shortcuts").querySelector("button") || card.querySelector("button");
    (firstButton || card).focus({ preventScroll: false });
    window.setTimeout(() => {
      $("inline-approval-panel").classList.remove("attention-pulse");
    }, 1200);
  }

  function buildApprovalCard(container, humanRequest, options = {}) {
    const prompt = humanRequest.prompt || humanRequest.message || "需要人工确认后继续。";
    const text = document.createElement("div");
    text.className = "approval-prompt";
    text.textContent = prompt;
    container.appendChild(text);
    const contextText = approvalContextText(humanRequest);
    if (contextText && !options.compact) {
      const note = document.createElement("div");
      note.className = "approval-note";
      note.textContent = contextText;
      container.appendChild(note);
    }
    const outline = state.lastFinalState?.report_outline || humanRequest.report_outline;
    if (outline && !options.compact) {
      const details = document.createElement("details");
      details.className = "approval-outline";
      const summary = document.createElement("summary");
      summary.textContent = "查看大纲";
      details.appendChild(summary);
      const pre = document.createElement("pre");
      pre.className = "code-box";
      pre.textContent = JSON.stringify(outline, null, 2);
      details.appendChild(pre);
      container.appendChild(details);
    }
    const actions = document.createElement("div");
    actions.className = "approve-grid";
    approvalActions(humanRequest).forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.approvalCommand = action.command;
      button.textContent = action.label;
      button.className = action.command === "cancel" ? "approval-cancel-btn" : "";
      button.setAttribute("aria-label", `审批选项：${action.label}`);
      button.addEventListener("click", () => approveCurrentJob(action.command, action.userText));
      actions.appendChild(button);
    });
    container.appendChild(actions);
  }

  function renderApprovalShortcuts(humanRequest) {
    const shortcuts = $("approval-shortcuts");
    shortcuts.innerHTML = "";
    if (!humanRequest) {
      shortcuts.className = "approval-shortcuts empty";
      const text = document.createElement("span");
      text.textContent = "No pending approval.";
      shortcuts.appendChild(text);
      return;
    }
    shortcuts.className = "approval-shortcuts";
    const label = document.createElement("span");
    label.textContent = "Pending approval:";
    shortcuts.appendChild(label);
    approvalActions(humanRequest).forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.approvalCommand = action.command;
      button.textContent = action.label;
      button.setAttribute("aria-label", `快捷审批：${action.label}`);
      button.addEventListener("click", () => approveCurrentJob(action.command, action.userText));
      shortcuts.appendChild(button);
    });
  }

  function upsertApprovalMessage(humanRequest) {
    const key = approvalKey(humanRequest);
    const existing = Array.from(document.querySelectorAll("[data-approval-key]")).find(
      (item) => item.dataset.approvalKey === key,
    );
    const article = existing || document.createElement("article");
    article.className = "message assistant-message approval-message";
    article.dataset.approvalKey = key;
    article.innerHTML = '<div class="message-meta">Assistant · 需要确认</div><div class="message-body"></div>';
    const body = article.querySelector(".message-body");
    body.innerHTML = "";
    buildApprovalCard(body, humanRequest);
    if (!existing) {
      $("message-list").appendChild(article);
      $("message-list").scrollTop = $("message-list").scrollHeight;
    }
  }

  function clearPendingApproval(message) {
    state.pendingHumanRequest = null;
    state.pendingApprovalKey = null;
    $("human-status").textContent = "idle";
    $("inline-approval-panel").classList.add("empty");
    $("human-request-card").className = "human-card empty";
    $("human-request-card").textContent = message || "暂无待确认请求";
    renderApprovalShortcuts(null);
  }

  function approvalActions(humanRequest) {
    const rawOptions = Array.isArray(humanRequest?.options) ? humanRequest.options : [];
    if (!rawOptions.length) {
      return DEFAULT_APPROVAL_ACTIONS;
    }
    const optionActions = rawOptions.map((option) => approvalActionFromOption(option));
    const merged = [...optionActions, ...DEFAULT_APPROVAL_ACTIONS];
    const seen = new Set();
    return merged.filter((action) => {
      const key = `${action.label}:${action.command}`;
      const commandSeen = action.command !== "report_confirm" && seen.has(action.command);
      if (seen.has(key) || commandSeen) {
        return false;
      }
      seen.add(key);
      seen.add(action.command);
      return true;
    });
  }

  function approvalActionFromOption(option) {
    const label = String(option || "").trim() || "Confirm";
    const normalized = label.toLowerCase().replaceAll(" ", "_");
    if (
      ["no", "cancel", "reject", "stop"].includes(normalized) ||
      normalized.includes("cancel")
    ) {
      return { label, command: "cancel", userText: "已取消本次确认。" };
    }
    if (normalized.includes("excel")) {
      return { label, command: "excel_confirm", userText: "已确认生成 Excel。" };
    }
    if (normalized.includes("ppt")) {
      return { label, command: "ppt_confirm", userText: "已确认生成 PPT。" };
    }
    if (normalized.includes("dashboard")) {
      return { label, command: "dashboard_confirm", userText: "已确认生成 Dashboard。" };
    }
    if (CONFIRM_COMMANDS.includes(normalized)) {
      return {
        label: approvalLabelForCommand(normalized),
        command: normalized,
        userText: approvalUserText(normalized),
      };
    }
    return { label, command: "report_confirm", userText: `已选择：${label}` };
  }

  function approvalLabelForCommand(command) {
    return (
      {
        dashboard_confirm: "Dashboard",
        excel_confirm: "Excel",
        ppt_confirm: "PPT",
        report_confirm: "Report",
      }[command] || command
    );
  }

  function approvalUserText(command) {
    return (
      DEFAULT_APPROVAL_ACTIONS.find((action) => action.command === command)?.userText ||
      `已确认 ${command}。`
    );
  }

  function approvalContextText(humanRequest) {
    const requestType = humanRequest.request_type || humanRequest.type || "";
    if (requestType) {
      return `Request type: ${requestType}`;
    }
    return "确认后将复用已有分析结果和大纲走导出 fast-path。";
  }

  function approvalKey(humanRequest) {
    return [
      state.currentJobId || "job",
      humanRequest.request_id || humanRequest.prompt || humanRequest.message || "approval",
    ].join(":");
  }

  function renderSql(finalState) {
    const hasPrimarySql =
      finalState?.intent === "direct_analysis" || finalState?.command === "analyze";
    if (!hasPrimarySql) {
      const multiQueryIntents = ["open_exploration", "schema_qa", "report_export"];
      $("sql-output").textContent = multiQueryIntents.includes(finalState?.intent)
        ? "该任务包含多个内部查询，请在开发者详情中查看。"
        : "未生成 SQL";
      $("sql-status").textContent = "empty";
      return;
    }
    const sql =
      finalState.sql_draft?.sql ||
      finalState.sql_draft?.query ||
      finalState.sql_result?.sql ||
      "";
    $("sql-output").textContent = sql || "未生成 SQL";
    $("sql-status").textContent = sql ? "ready" : "empty";
  }

  function renderRouterDecision(decision) {
    if (!decision || typeof decision !== "object") {
      return;
    }
    state.routerDecision = decision;
    const source = decision.source || "unknown";
    const confidence =
      decision.confidence === null || decision.confidence === undefined
        ? "n/a"
        : Number(decision.confidence).toFixed(2);
    $("router-decision-source").textContent = source;
    $("router-decision-intent").textContent = decision.intent || "unknown";
    $("router-decision-confidence").textContent = confidence;
    $("router-decision-reason").textContent = decision.reason || "No router reason.";
  }

  function clearRouterDecision() {
    $("router-decision-source").textContent = "none";
    $("router-decision-intent").textContent = "unknown";
    $("router-decision-confidence").textContent = "n/a";
    $("router-decision-reason").textContent = "暂无路由决策";
  }

  function renderContextSummary(summary) {
    const status = $("context-summary-status");
    if (!status) {
      return;
    }
    if (!summary || typeof summary !== "object") {
      status.textContent = "empty";
      $("context-summary-datasource").textContent = "none";
      $("context-summary-intent").textContent = "unknown";
      $("context-summary-field-count").textContent = "0";
      $("context-summary-artifacts").textContent = "0";
      $("context-summary-pending").textContent = "none";
      return;
    }
    const knownFields = Array.isArray(summary.known_fields) ? summary.known_fields : [];
    const artifactRefs = Array.isArray(summary.latest_artifact_refs)
      ? summary.latest_artifact_refs
      : [];
    status.textContent = "ready";
    $("context-summary-datasource").textContent = summary.current_datasource_id || "none";
    $("context-summary-intent").textContent = summary.last_user_intent || "unknown";
    $("context-summary-field-count").textContent = String(knownFields.length);
    $("context-summary-artifacts").textContent = String(artifactRefs.length);
    $("context-summary-pending").textContent = summary.pending_human_request
      ? summary.pending_human_request.request_type || "pending"
      : "none";
  }

  function collectArtifacts(payload) {
    extractArtifactRefs(payload).forEach((ref) => {
      const current = state.artifacts.get(ref) || { artifact_ref: ref, metadata: null };
      const inlineMetadata = artifactMetadataFromPayload(payload, ref);
      state.artifacts.set(ref, {
        ...current,
        metadata: current.metadata || inlineMetadata,
      });
    });
  }

  function renderArtifacts() {
    const list = $("artifact-list");
    $("artifact-count").textContent = String(state.artifacts.size);
    if (!state.artifacts.size) {
      list.innerHTML =
        '<div class="muted-note">分析完成后，图表、报告、PPT、Excel 和 Dashboard 会出现在这里。</div>';
      return;
    }
    list.innerHTML = "";
    artifactGroups().forEach((group) => {
      const records = Array.from(state.artifacts.entries()).filter(([, record]) =>
        group.kinds.includes(artifactKind(record)),
      );
      if (!records.length) {
        return;
      }
      const section = document.createElement("section");
      section.className = `artifact-group artifact-group-${group.key}`;
      section.innerHTML = `
        <div class="artifact-group-title">
          <span>${escapeHtml(group.title)}</span>
          <span>${records.length}</span>
        </div>
      `;
      records.forEach(([ref, record]) => {
        section.appendChild(renderArtifactItem(ref, record));
      });
      list.appendChild(section);
    });
    state.artifacts.forEach((record, ref) => {
      queueArtifactMetadataLoad(ref, record);
    });
  }

  function renderArtifactItem(ref, record) {
    const kind = artifactKind(record);
    const item = document.createElement("article");
    item.className = "artifact-item";
    item.innerHTML = `
      <div class="artifact-title">
        <span>${escapeHtml(ref)}</span>
        <span class="artifact-kind artifact-kind-${escapeHtml(kind)}">${escapeHtml(
          artifactKindLabel(kind),
        )}</span>
      </div>
      <div class="artifact-meta">${escapeHtml(artifactMimeType(record) || "metadata pending")}</div>
      <div class="artifact-actions"></div>
    `;
    const actions = item.querySelector(".artifact-actions");
    addArtifactButton(actions, "metadata", () => loadArtifactMetadata(ref), `View artifact metadata for ${ref}`);
    if (kind === "dashboard") {
      addArtifactButton(actions, "Render dashboard", () => renderDashboardArtifact(ref), `Render dashboard ${ref}`);
      addArtifactDownload(actions, ref, "Download JSON");
    } else if (kind === "chart") {
      addArtifactButton(actions, "Preview chart", () => previewChartArtifact(ref), `Preview chart ${ref}`);
      addArtifactDownload(actions, ref, "Download JSON");
    } else if (kind === "json" || kind === "unknown" || kind === "loading") {
      addArtifactButton(actions, "preview JSON", () => previewArtifactContent(ref), `Preview artifact JSON ${ref}`);
      addArtifactDownload(actions, ref, "Download content");
    } else {
      addArtifactDownload(actions, ref, "Download content");
    }
    return item;
  }

  function artifactGroups() {
    return [
      { key: "charts", title: "Charts", kinds: ["chart"] },
      { key: "reports", title: "Reports", kinds: ["report"] },
      { key: "excel", title: "Excel", kinds: ["excel"] },
      { key: "ppt", title: "PPT", kinds: ["ppt"] },
      { key: "dashboards", title: "Dashboards", kinds: ["dashboard"] },
      { key: "other", title: "Other artifacts", kinds: ["json", "unknown", "loading"] },
    ];
  }

  function addArtifactButton(container, label, onClick, ariaLabel = null) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-label", ariaLabel || label);
    button.addEventListener("click", onClick);
    container.appendChild(button);
  }

  function addArtifactDownload(container, ref, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-label", `${label} for ${ref}`);
    button.addEventListener("click", () => downloadArtifact(ref));
    container.appendChild(button);
  }

  function queueArtifactMetadataLoad(ref, record) {
    if (record.metadata || record.metadataLoading || record.metadataError) {
      return;
    }
    state.artifacts.set(ref, { ...record, metadataLoading: true });
    ensureArtifactMetadata(ref, { silent: true }).catch(() => {
      state.artifacts.set(ref, { ...record, metadataLoading: false, metadataError: true });
      renderArtifacts();
    });
  }

  async function loadArtifactMetadata(ref, options = {}) {
    try {
      const metadata = await ensureArtifactMetadata(ref, options);
      if (!options.silent) {
        $("artifact-preview-kind").textContent = "metadata";
        $("artifact-preview").textContent = JSON.stringify(metadata, null, 2);
      }
      return metadata;
    } catch (error) {
      if (!options.silent) {
        pushError(`Artifact metadata failed: ${error.message}`);
      }
      return null;
    }
  }

  async function ensureArtifactMetadata(ref, options = {}) {
    const normalizedRef = normalizeArtifactRef(ref);
    const current = state.artifacts.get(normalizedRef) || state.artifacts.get(ref);
    if (current?.metadata) {
      return current.metadata;
    }
    const artifactId = artifactIdFromRef(ref);
    const metadata = await fetchJson(`/artifacts/${encodeURIComponent(artifactId)}`);
    const nextRef = normalizeArtifactRef(metadata.artifact_ref || ref);
    if (nextRef !== ref && state.artifacts.has(ref)) {
      state.artifacts.delete(ref);
    }
    state.artifacts.set(nextRef, {
      artifact_ref: nextRef,
      metadata,
      metadataLoading: false,
    });
    if (options.refresh !== false) {
      renderArtifacts();
    }
    return metadata;
  }

  async function previewArtifactContent(ref) {
    try {
      const metadata = await ensureArtifactMetadata(ref);
      const { text, mimeType } = await fetchArtifactContent(ref, metadata);
      $("artifact-preview-kind").textContent = mimeType || "content";
      if (mimeType.includes("json") || mimeType.includes("text") || mimeType.includes("html")) {
        $("artifact-preview").textContent = limitText(text, 5000);
      } else {
        $("artifact-preview").textContent =
          "Binary artifact. Use the download button to save the file.";
      }
    } catch (error) {
      pushError(`Artifact preview failed: ${error.message}`);
    }
  }

  async function renderDashboardArtifact(ref) {
    try {
      $("dashboard-renderer-status").textContent = "loading";
      const metadata = await ensureArtifactMetadata(ref);
      const { json } = await fetchArtifactContent(ref, metadata);
      if (!json || typeof json !== "object") {
        throw new Error("Dashboard artifact content is not a JSON object.");
      }
      renderDashboardSpec(json, ref);
      $("artifact-preview-kind").textContent = "dashboard";
      $("artifact-preview").textContent = JSON.stringify(json, null, 2);
      $("dashboard-renderer").focus({ preventScroll: false });
    } catch (error) {
      $("dashboard-renderer-status").textContent = "error";
      pushError(`Dashboard render failed: ${error.message}`);
    }
  }

  async function previewChartArtifact(ref, targetElement = null) {
    try {
      if (!targetElement) {
        $("dashboard-renderer-status").textContent = "loading";
      }
      const metadata = await ensureArtifactMetadata(ref);
      const { json } = await fetchArtifactContent(ref, metadata);
      if (!json || typeof json !== "object") {
        throw new Error("Chart artifact content is not a JSON object.");
      }
      const target = targetElement || $("dashboard-renderer");
      target.className = targetElement ? target.className : "dashboard-renderer";
      target.innerHTML = "";
      renderChartPreviewFromSpec(json, target);
      if (!targetElement) {
        $("dashboard-renderer-status").textContent = "chart";
        $("artifact-preview-kind").textContent = "chart";
        $("artifact-preview").textContent = JSON.stringify(json, null, 2);
        $("dashboard-renderer").focus({ preventScroll: false });
      }
    } catch (error) {
      if (!targetElement) {
        $("dashboard-renderer-status").textContent = "error";
      }
      pushError(`Chart preview failed: ${error.message}`);
    }
  }

  async function downloadArtifact(ref) {
    try {
      const metadata = await ensureArtifactMetadata(ref);
      const artifactId = artifactIdFromRef(ref);
      const response = await fetch(
        `${state.baseUrl}/artifacts/${encodeURIComponent(artifactId)}/content`,
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = downloadName(metadata, artifactId);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      pushError(`Artifact download failed: ${error.message}`);
    }
  }

  async function fetchArtifactContent(ref, metadata) {
    const artifactId = artifactIdFromRef(ref);
    const response = await fetch(
      `${state.baseUrl}/artifacts/${encodeURIComponent(artifactId)}/content`,
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const mimeType =
      metadata?.mime_type ||
      nestedArtifactMetadata(metadata).mime_type ||
      response.headers.get("content-type") ||
      "";
    const text = await response.text();
    let json = null;
    if (mimeType.includes("json")) {
      json = text ? JSON.parse(text) : null;
    }
    return { text, json, mimeType };
  }

  function renderDashboardSpec(spec, ref) {
    const renderer = $("dashboard-renderer");
    renderer.className = "dashboard-renderer";
    renderer.innerHTML = "";
    $("dashboard-renderer-status").textContent = "rendered";

    const header = document.createElement("div");
    header.className = "dashboard-header";
    header.innerHTML = `
      <div>
        <div class="dashboard-kicker">${escapeHtml(ref)}</div>
        <h2>${escapeHtml(spec.title || "Dashboard")}</h2>
      </div>
      <span>${escapeHtml(String((spec.widgets || []).length))} widget(s)</span>
    `;
    renderer.appendChild(header);

    const summary = document.createElement("p");
    summary.className = "dashboard-summary";
    summary.textContent = spec.summary || spec.question || "Dashboard spec rendered from artifact content.";
    renderer.appendChild(summary);

    if (Array.isArray(spec.filters) && spec.filters.length) {
      const filters = document.createElement("div");
      filters.className = "dashboard-filters";
      spec.filters.slice(0, 6).forEach((filter) => {
        const chip = document.createElement("span");
        chip.textContent = filter.label || filter.field || "filter";
        filters.appendChild(chip);
      });
      renderer.appendChild(filters);
    }

    const grid = document.createElement("div");
    grid.className = "dashboard-grid";
    (spec.widgets || []).forEach((widget) => {
      grid.appendChild(renderDashboardWidget(widget));
    });
    if (!spec.widgets?.length) {
      const empty = document.createElement("div");
      empty.className = "muted-note";
      empty.textContent = "Dashboard spec has no widgets.";
      grid.appendChild(empty);
    }
    renderer.appendChild(grid);
  }

  function renderDashboardWidget(widget) {
    const card = document.createElement("article");
    const widgetType = String(widget.widget_type || widget.type || "text").toLowerCase();
    card.className = `dashboard-widget dashboard-widget-${widgetType}`;
    applyWidgetLayout(card, widget.layout);

    const title = document.createElement("h3");
    title.textContent = widget.title || widget.metric_name || widgetType;
    card.appendChild(title);

    if (widgetType === "metric") {
      const value = document.createElement("div");
      value.className = "metric-value";
      value.textContent = formatMetricValue(widget.value ?? widget.metric_value);
      card.appendChild(value);
      appendWidgetDescription(card, widget);
      return card;
    }

    if (widgetType === "chart" && widget.chart_artifact_ref) {
      const chartTarget = document.createElement("div");
      chartTarget.className = "chart-preview-container";
      chartTarget.textContent = "Loading chart artifact...";
      card.appendChild(chartTarget);
      previewChartArtifact(widget.chart_artifact_ref, chartTarget);
      appendWidgetDescription(card, widget);
      return card;
    }

    if (widgetType === "table") {
      card.appendChild(renderTablePreview(widget));
      appendWidgetDescription(card, widget);
      return card;
    }

    if (widgetType === "insight" || widgetType === "text") {
      card.appendChild(renderTextWidget(widget));
      return card;
    }

    const fallback = document.createElement("pre");
    fallback.className = "code-box compact";
    fallback.textContent = limitText(JSON.stringify(widget, null, 2), 2000);
    card.appendChild(fallback);
    return card;
  }

  function applyWidgetLayout(card, layout) {
    if (!layout || typeof layout !== "object") {
      return;
    }
    card.style.gridColumn = `span ${Math.min(Math.max(Number(layout.w || 4), 3), 12)}`;
    card.style.minHeight = `${Math.min(Math.max(Number(layout.h || 3), 2), 6) * 70}px`;
  }

  function renderTablePreview(widget) {
    const wrapper = document.createElement("div");
    wrapper.className = "table-preview";
    const rows = widget.table_preview || widget.metadata?.preview_rows || [];
    if (Array.isArray(rows) && rows.length) {
      const columns = Object.keys(rows[0]).slice(0, 6);
      const table = document.createElement("table");
      table.innerHTML = `
        <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
        <tbody>${rows
          .slice(0, 8)
          .map(
            (row) =>
              `<tr>${columns
                .map((column) => `<td>${escapeHtml(row[column])}</td>`)
                .join("")}</tr>`,
          )
          .join("")}</tbody>
      `;
      wrapper.appendChild(table);
      return wrapper;
    }
    const columns = widget.metadata?.columns || [];
    wrapper.innerHTML = `
      <div class="muted-note">Preview rows are not embedded in the dashboard artifact.</div>
      <div>${escapeHtml(Number(widget.metadata?.row_count || 0))} row(s)</div>
      <div>${escapeHtml(Array.isArray(columns) ? columns.join(", ") : "")}</div>
    `;
    return wrapper;
  }

  function renderTextWidget(widget) {
    const wrapper = document.createElement("div");
    wrapper.className = "text-widget";
    const insights = widget.metadata?.insights;
    const sections = widget.metadata?.sections;
    if (Array.isArray(insights) && insights.length) {
      insights.slice(0, 4).forEach((insight) => {
        const item = document.createElement("p");
        item.innerHTML = `<strong>${escapeHtml(insight.title || "Insight")}</strong><br>${escapeHtml(
          insight.summary || "",
        )}`;
        wrapper.appendChild(item);
      });
      return wrapper;
    }
    if (Array.isArray(sections) && sections.length) {
      sections.slice(0, 4).forEach((section) => {
        const item = document.createElement("p");
        item.innerHTML = `<strong>${escapeHtml(section.title || "Section")}</strong><br>${escapeHtml(
          (section.points || []).join(" "),
        )}`;
        wrapper.appendChild(item);
      });
      return wrapper;
    }
    wrapper.textContent = widget.description || widget.text || "No text content.";
    return wrapper;
  }

  function renderChartPreviewFromSpec(chartArtifact, container) {
    const normalized = normalizeChartArtifact(chartArtifact);
    if (!normalized.rows.length || !normalized.yField) {
      renderChartFallback(chartArtifact, container, "Chart data is unavailable.");
      return;
    }
    if (!["line", "bar"].includes(normalized.chartType)) {
      renderChartFallback(
        chartArtifact,
        container,
        `Chart type ${normalized.chartType || "unknown"} is not supported yet.`,
      );
      return;
    }
    const values = normalized.rows
      .map((row) => Number(row[normalized.yField]))
      .filter((value) => Number.isFinite(value));
    if (!values.length) {
      renderChartFallback(chartArtifact, container, "No numeric values for chart preview.");
      return;
    }
    const labels = normalized.rows.map((row, index) =>
      String(row[normalized.xField] ?? index + 1),
    );
    const maxValue = Math.max(...values, 0);
    const minValue = Math.min(...values, 0);
    const span = maxValue === minValue ? 1 : maxValue - minValue;
    const width = 360;
    const height = 210;
    const pad = 34;
    const plotWidth = width - pad * 2;
    const plotHeight = height - pad * 2;
    const points = values.map((value, index) => {
      const x =
        pad + (values.length === 1 ? plotWidth / 2 : (index / (values.length - 1)) * plotWidth);
      const y = height - pad - ((value - minValue) / span) * plotHeight;
      return { x, y, value, label: labels[index] };
    });
    const markups =
      normalized.chartType === "bar" ? barMarkup(points, plotWidth, pad, height) : lineMarkup(points);
    container.innerHTML = `
      <div class="chart-preview-title">${escapeHtml(normalized.title || "Chart preview")}</div>
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
        <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" />
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" />
        ${markups}
        <text x="${pad}" y="${height - 8}">${escapeHtml(labels[0] || "")}</text>
        <text x="${width - pad}" y="${height - 8}" text-anchor="end">${escapeHtml(
          labels.at(-1) || "",
        )}</text>
        <text x="${pad + 4}" y="${pad - 10}">${escapeHtml(formatMetricValue(maxValue))}</text>
      </svg>
    `;
  }

  function normalizeChartArtifact(chartArtifact) {
    const chart = chartArtifact.chart || chartArtifact.chart_spec || chartArtifact;
    const data = chartArtifact.data || chartArtifact.dataset || {};
    const rows = Array.isArray(data.rows)
      ? data.rows
      : Array.isArray(chartArtifact.rows)
        ? chartArtifact.rows
        : [];
    const columns = Array.isArray(data.columns)
      ? data.columns.map((column) => column.name || column)
      : rows[0]
        ? Object.keys(rows[0])
        : [];
    const xField = chart.x || chart.encoding?.x || inferCategoryField(rows, columns);
    const yField = chart.y || chart.encoding?.y || inferNumericField(rows, columns, xField);
    return {
      chartType: String(chart.chart_type || chart.type || "").toLowerCase(),
      title: chart.title,
      rows: rows.slice(0, 24),
      xField,
      yField,
    };
  }

  function inferCategoryField(rows, columns) {
    return (
      columns.find((column) => rows.some((row) => !isNumericValue(row[column]))) ||
      columns[0] ||
      null
    );
  }

  function inferNumericField(rows, columns, exceptField) {
    return (
      columns.find(
        (column) => column !== exceptField && rows.some((row) => isNumericValue(row[column])),
      ) || null
    );
  }

  function isNumericValue(value) {
    return value !== null && value !== "" && Number.isFinite(Number(value));
  }

  function lineMarkup(points) {
    const path = points.map((point) => `${point.x},${point.y}`).join(" ");
    const circles = points
      .map(
        (point) =>
          `<circle cx="${point.x}" cy="${point.y}" r="3"><title>${escapeHtml(
            `${point.label}: ${point.value}`,
          )}</title></circle>`,
      )
      .join("");
    return `<polyline points="${path}" fill="none" />${circles}`;
  }

  function barMarkup(points, plotWidth, pad, height) {
    const barWidth = Math.max(8, Math.min(34, plotWidth / Math.max(points.length, 1) - 6));
    return points
      .map((point) => {
        const barHeight = height - pad - point.y;
        return `<rect x="${point.x - barWidth / 2}" y="${point.y}" width="${barWidth}" height="${barHeight}"><title>${escapeHtml(
          `${point.label}: ${point.value}`,
        )}</title></rect>`;
      })
      .join("");
  }

  function renderChartFallback(chartArtifact, container, reason) {
    container.innerHTML = `
      <div class="muted-note">${escapeHtml(reason)}</div>
      <pre class="code-box compact">${escapeHtml(limitText(JSON.stringify(chartArtifact, null, 2), 2400))}</pre>
    `;
  }

  function appendWidgetDescription(card, widget) {
    if (!widget.description) {
      return;
    }
    const description = document.createElement("p");
    description.className = "widget-description";
    description.textContent = widget.description;
    card.appendChild(description);
  }

  function clearDashboardRenderer() {
    const renderer = $("dashboard-renderer");
    if (!renderer) {
      return;
    }
    renderer.className = "dashboard-renderer empty";
    renderer.textContent = "Select a dashboard artifact and click Render dashboard.";
    $("dashboard-renderer-status").textContent = "idle";
  }

  function artifactMetadataFromPayload(payload, ref) {
    if (!payload || typeof payload !== "object") {
      return null;
    }
    const rawRef = payload.artifact_ref || payload.chart_artifact_ref || payload.artifact_id;
    if (!rawRef || normalizeArtifactRef(rawRef) !== ref || typeof payload.metadata !== "object") {
      return null;
    }
    return {
      artifact_id: artifactIdFromRef(ref),
      artifact_ref: ref,
      metadata: payload.metadata,
      mime_type: payload.mime_type || payload.metadata.mime_type || null,
      content_type: payload.content_type || null,
    };
  }

  function artifactKind(record) {
    const metadata = record.metadata || {};
    const nested = nestedArtifactMetadata(metadata);
    const mimeType = artifactMimeType(record).toLowerCase();
    const reportFormat = String(nested.report_format || metadata.report_format || "").toLowerCase();
    const reportType = String(nested.report_type || metadata.report_type || "").toLowerCase();
    const artifactKindValue = String(nested.artifact_kind || nested.artifact_type || "").toLowerCase();
    if (
      reportFormat === "dashboard" ||
      reportType.includes("dashboard") ||
      nested.tool_name === "generate_dashboard"
    ) {
      return "dashboard";
    }
    if (
      artifactKindValue === "chart" ||
      mimeType.includes(CHART_ARTIFACT_MIME) ||
      mimeType.includes("chart+json") ||
      nested.chart_type
    ) {
      return "chart";
    }
    if (mimeType.includes("spreadsheet")) {
      return "excel";
    }
    if (mimeType.includes("presentation")) {
      return "ppt";
    }
    if (reportFormat === "report" || mimeType.includes("markdown") || mimeType.includes("html")) {
      return "report";
    }
    if (mimeType.includes("json")) {
      return "json";
    }
    return record.metadataLoading ? "loading" : "unknown";
  }

  function artifactKindLabel(kind) {
    return {
      chart: "chart",
      dashboard: "dashboard",
      excel: "excel",
      json: "json",
      loading: "loading",
      ppt: "ppt",
      report: "report",
      unknown: "unknown",
    }[kind];
  }

  function artifactMimeType(record) {
    const metadata = record.metadata || {};
    const nested = nestedArtifactMetadata(metadata);
    return String(metadata.mime_type || nested.mime_type || "");
  }

  function nestedArtifactMetadata(metadata) {
    if (metadata?.metadata && typeof metadata.metadata === "object") {
      return metadata.metadata;
    }
    return {};
  }

  function formatMetricValue(value) {
    if (value === null || value === undefined || value === "") {
      return "n/a";
    }
    const numberValue = Number(value);
    if (Number.isFinite(numberValue)) {
      return numberValue.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(value);
  }

  async function fetchJson(path, options = {}) {
    const init = {
      method: options.method || "GET",
      headers: {
        Accept: "application/json",
      },
    };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json; charset=utf-8";
      init.body = JSON.stringify(options.body);
    }
    let response;
    try {
      response = await fetch(`${state.baseUrl}${path}`, init);
    } catch (error) {
      throw new Error(friendlyNetworkError(error));
    }
    const text = await response.text();
    const data = parseResponseJson(text);
    if (!response.ok) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }
    return data;
  }

  async function fetchFormData(path, formData) {
    let response;
    try {
      response = await fetch(`${state.baseUrl}${path}`, {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
        body: formData,
      });
    } catch (error) {
      throw new Error(friendlyNetworkError(error));
    }
    const text = await response.text();
    const data = parseResponseJson(text);
    if (!response.ok) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }
    return data;
  }

  function parseResponseJson(text) {
    if (!text) {
      return null;
    }
    try {
      return JSON.parse(text);
    } catch (error) {
      return { detail: text || error.message };
    }
  }

  function friendlyNetworkError(error) {
    const message = error?.message || "request failed";
    if (message.includes("Failed to fetch") || message.includes("NetworkError")) {
      return "后端未连接，请确认 FastAPI 已启动并检查 API Base URL。";
    }
    return message;
  }

  function addTimelineRow(eventType, eventData) {
    const row = document.createElement("article");
    row.className = `event-row ${eventType}`;
    const nodeName = eventData.node_name || eventData.tool_name || "";
    const message = eventData.message || JSON.stringify(eventData.payload || {});
    row.innerHTML = `
      <div class="event-title">
        <span>${escapeHtml(eventType)}</span>
        <span>${escapeHtml(nodeName)}</span>
      </div>
      <div class="event-body">${escapeHtml(limitText(message, 260))}</div>
    `;
    $("event-timeline").appendChild(row);
    $("event-timeline").scrollTop = $("event-timeline").scrollHeight;
  }

  function renderProgressDelta(message) {
    const text = String(message || "").trim();
    if (!text) {
      return;
    }
    if (!state.progressMessageId) {
      const article = appendMessage("assistant", text, { progress: true });
      state.progressMessageId = article.dataset.messageId;
      return;
    }
    const article = document.querySelector(
      `[data-message-id="${CSS.escape(state.progressMessageId)}"]`,
    );
    if (article) {
      article.querySelector(".message-body").textContent = text;
      $("message-list").scrollTop = $("message-list").scrollHeight;
    }
  }

  function clearProgressDelta() {
    if (!state.progressMessageId) {
      return;
    }
    const article = document.querySelector(
      `[data-message-id="${CSS.escape(state.progressMessageId)}"]`,
    );
    if (article) {
      article.remove();
    }
    state.progressMessageId = null;
  }

  function collectTiming(eventType, eventData) {
    const payload = eventData.payload || {};
    if (!["node_end", "llm_end", "llm_error"].includes(eventType)) {
      return;
    }
    if (!Number.isFinite(Number(payload.duration_ms))) {
      return;
    }
    state.timingRows.push({
      name: eventData.node_name || payload.node_name || eventType,
      kind: eventType.startsWith("llm_") ? "llm" : "node",
      duration_ms: Number(payload.duration_ms),
      status: payload.status || (eventType === "llm_error" ? "error" : "completed"),
      metadata: payload,
    });
    renderTimingPanel();
  }

  function collectTimingFromFinalState(finalState) {
    const records = Array.isArray(finalState?.timing_records)
      ? finalState.timing_records
      : [];
    if (!records.length) {
      return;
    }
    const llmRows = state.timingRows.filter((row) => row.kind === "llm");
    state.timingRows = records
      .filter((record) => Number.isFinite(Number(record.duration_ms)))
      .map((record) => ({
        name: record.node_name,
        kind: record.metadata?.kind || "node",
        duration_ms: Number(record.duration_ms),
        status: record.status || "completed",
        metadata: record.metadata || {},
      }))
      .concat(llmRows);
  }

  function renderTimingPanel() {
    const table = $("timing-table-body");
    if (!table) {
      return;
    }
    const rows = [...state.timingRows].sort((left, right) => right.duration_ms - left.duration_ms);
    const total = rows.reduce((sum, row) => sum + row.duration_ms, 0);
    const llmTotal = rows
      .filter((row) => row.kind === "llm")
      .reduce((sum, row) => sum + row.duration_ms, 0);
    $("timing-total-duration").textContent = `${Math.round(total)} ms`;
    $("timing-llm-duration").textContent = `${Math.round(llmTotal)} ms`;
    if (!rows.length) {
      table.innerHTML = '<tr><td colspan="4">暂无 timing 数据</td></tr>';
      return;
    }
    table.innerHTML = "";
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(row.name)}</td>
        <td>${escapeHtml(row.kind)}</td>
        <td>${Math.round(row.duration_ms)}</td>
        <td>${escapeHtml(row.status || "completed")}</td>
      `;
      table.appendChild(tr);
    });
  }

  function appendMessage(role, text, options = {}) {
    const article = document.createElement("article");
    article.className = `message ${role}-message${options.error ? " error" : ""}${
      options.progress ? " progress" : ""
    }`;
    article.dataset.messageId = `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    article.innerHTML = `
      <div class="message-meta">${role === "user" ? "User" : "Assistant"}</div>
      <div class="message-body"></div>
    `;
    article.querySelector(".message-body").textContent = text;
    $("message-list").appendChild(article);
    $("message-list").scrollTop = $("message-list").scrollHeight;
    return article;
  }

  function appendSchemaQaMessage(result, fallbackText = "") {
    const article = appendMessage("assistant", result?.answer || fallbackText || "已整理字段说明。");
    const body = article.querySelector(".message-body");
    if (!result || !Array.isArray(result.tables)) {
      return article;
    }
    const card = document.createElement("section");
    card.className = "schema-qa-card";
    card.setAttribute("aria-label", "字段说明");
    const tableHtml = result.tables
      .map((table) => `
        <div class="schema-qa-table">
          <div class="schema-qa-table-title">${escapeHtml(table.table_name || "table")}${
            table.row_count !== null && table.row_count !== undefined
              ? ` · ${escapeHtml(String(table.row_count))} 行`
              : ""
          }</div>
          <div class="schema-qa-fields">
            ${(table.fields || [])
              .map((field) => `
                <div class="schema-qa-field">
                  <strong>${escapeHtml(field.field_name || "")}</strong>
                  <span>${escapeHtml(field.data_type || "unknown")}</span>
                  <small>${escapeHtml((field.sample_values || []).slice(0, 2).join(" / "))}</small>
                </div>
              `)
              .join("")}
          </div>
        </div>
      `)
      .join("");
    const metricText = (result.candidate_metrics || []).join("、") || "暂无";
    const dimensionText = (result.candidate_dimensions || []).join("、") || "暂无";
    const suggestionText = (result.analysis_suggestions || []).join("；") || "可以先询问字段含义或发起明确分析问题。";
    card.innerHTML = `
      <div class="schema-qa-summary">
        <div><strong>候选指标</strong><span>${escapeHtml(metricText)}</span></div>
        <div><strong>候选维度</strong><span>${escapeHtml(dimensionText)}</span></div>
        <div><strong>可分析方向</strong><span>${escapeHtml(suggestionText)}</span></div>
      </div>
      ${tableHtml}
    `;
    body.appendChild(card);
    $("message-list").scrollTop = $("message-list").scrollHeight;
    return article;
  }

  function pushError(message) {
    pushIssue(message, "error");
  }

  function pushWarning(message) {
    pushIssue(message, "warning");
  }

  function pushIssue(message, kind) {
    if (!message) {
      return;
    }
    const last = state.errors[state.errors.length - 1];
    if (last?.message === message && last?.kind === kind) {
      return;
    }
    state.errors.push({ message, kind });
    renderErrors();
  }

  function renderErrors() {
    $("error-count").textContent = String(state.errors.length);
    $("error-list").innerHTML = "";
    state.errors.slice(-8).forEach((entry) => {
      const item = document.createElement("div");
      const normalized = typeof entry === "string" ? { message: entry, kind: "error" } : entry;
      item.className = `error-item ${normalized.kind === "warning" ? "warning-item" : ""}`;
      const label = document.createElement("strong");
      label.textContent = normalized.kind === "warning" ? "Warning: " : "Error: ";
      const message = document.createElement("span");
      message.textContent = normalized.message;
      item.append(label, message);
      $("error-list").appendChild(item);
    });
  }

  function eventSummary(eventData) {
    const node = eventData.node_name || eventData.tool_name || eventData.event_type || "event";
    const message = eventData.message || eventData.error_message || "";
    const payload = eventData.payload && typeof eventData.payload === "object"
      ? JSON.stringify(sanitizeEventPayload(eventData.payload))
      : "";
    return limitText([node, message, payload].filter(Boolean).join(" · "), 420);
  }

  function parseEventData(rawData) {
    try {
      return JSON.parse(rawData || "{}");
    } catch (error) {
      return { event_type: "message", message: rawData, payload: { parse_error: error.message } };
    }
  }

  function sanitizeEventPayload(value) {
    if (Array.isArray(value)) {
      return value.map((item) => sanitizeEventPayload(item));
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [
          key,
          OMITTED_PAYLOAD_KEYS.has(key) ? "<omitted>" : sanitizeEventPayload(item),
        ]),
      );
    }
    return value;
  }

  function extractArtifactRefs(value) {
    const refs = [];
    visit(value);
    return Array.from(new Set(refs));

    function visit(item) {
      if (Array.isArray(item)) {
        item.forEach(visit);
        return;
      }
      if (!item || typeof item !== "object") {
        return;
      }
      Object.entries(item).forEach(([key, child]) => {
        if (
          ["artifact_ref", "chart_artifact_ref"].includes(key) &&
          typeof child === "string"
        ) {
          refs.push(normalizeArtifactRef(child));
        } else if (
          ["artifact_refs", "chart_artifact_refs"].includes(key) &&
          Array.isArray(child)
        ) {
          child
            .filter((ref) => typeof ref === "string")
            .forEach((ref) => refs.push(normalizeArtifactRef(ref)));
        } else if (key === "artifact_id" && typeof child === "string") {
          refs.push(normalizeArtifactRef(child));
        } else {
          visit(child);
        }
      });
    }
  }

  function normalizeArtifactRef(refOrId) {
    return `artifact:${artifactIdFromRef(refOrId)}`;
  }

  function artifactIdFromRef(refOrId) {
    const value = String(refOrId || "").trim();
    if (!value) {
      return "";
    }
    return value.split(":").filter(Boolean).at(-1);
  }

  function downloadName(metadata, artifactId) {
    const nested = nestedArtifactMetadata(metadata);
    const stem = safeFileStem(
      nested.title ||
        metadata?.title ||
        nested.report_type ||
        nested.artifact_kind ||
        artifactId,
    );
    const mimeType = metadata?.mime_type || nested.mime_type || "";
    if (mimeType.includes("spreadsheet")) {
      return `${stem}.xlsx`;
    }
    if (mimeType.includes("presentation")) {
      return `${stem}.pptx`;
    }
    if (mimeType.includes("markdown")) {
      return `${stem}.md`;
    }
    if (mimeType.includes("html")) {
      return `${stem}.html`;
    }
    if (mimeType.includes("json")) {
      return `${stem}.json`;
    }
    return stem;
  }

  function safeFileStem(value) {
    return (
      String(value || "artifact")
        .trim()
        .replace(/[\\/:*?"<>|]+/g, "-")
        .replace(/\s+/g, "-")
        .slice(0, 80) || "artifact"
    );
  }

  function closeEventSource() {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
  }

  function setBusy(isBusy, label) {
    state.isBusy = Boolean(isBusy);
    $("request-status").textContent = label;
    $("request-status").classList.toggle("is-loading", Boolean(isBusy));
    updateComposerAvailability();
  }

  function updateComposerAvailability() {
    const hasSession = Boolean(state.sessionId);
    const backendUnavailable = state.apiReachable === false;
    const inputDisabled = !hasSession || backendUnavailable || state.isSubmitting;
    const sendDisabled = inputDisabled || state.isBusy;
    $("message-input").disabled = inputDisabled;
    $("send-btn").disabled = sendDisabled;
    if (!hasSession) {
      $("message-input").placeholder = "请先新建会话";
    } else if (backendUnavailable) {
      $("message-input").placeholder = "后端未连接，请先启动 FastAPI";
    } else if (state.isSubmitting) {
      $("message-input").placeholder = "正在发送，请稍候...";
    } else {
      $("message-input").placeholder = "输入问题，Enter 发送，Shift+Enter 换行";
    }
  }

  function normalizeBaseUrl(value) {
    return (value || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
  }

  function optionalRuntimeLabel(runtime) {
    const parts = [];
    if (runtime.celery) {
      parts.push(`celery:${runtime.celery}`);
    }
    if (runtime.redis) {
      parts.push(`redis:${runtime.redis}`);
    }
    if (runtime.llm_provider) {
      parts.push(`llm:${runtime.llm_provider}`);
    }
    return parts.length ? parts.join(" ") : "optional";
  }

  function datasourceStatusLabel(runtime) {
    if (Number.isInteger(runtime.datasource_count)) {
      return `${runtime.datasource_count} registered`;
    }
    if (runtime.data_source_configured === true) {
      return "configured";
    }
    if (runtime.datasource_id) {
      return runtime.datasource_id;
    }
    return "demo/default";
  }

  function llmModeLabel(runtime) {
    if (runtime.llm_mode) {
      return runtime.llm_mode;
    }
    if (runtime.llm_provider || runtime.model) {
      return "real-llm";
    }
    return "rule";
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function limitText(value, limit) {
    const text = String(value ?? "");
    return text.length > limit ? `${text.slice(0, limit)}...<truncated>` : text;
  }

  // Static tests inspect these helpers to keep artifact:<id> and SSE contracts stable.
  window.DataAnalysisWebUI = {
    artifactIdFromRef,
    clearDashboardRenderer,
    downloadArtifact,
    extractArtifactRefs,
    loadSession,
    normalizeArtifactRef,
    previewChartArtifact,
    registerFilePathDatasource,
    refreshDatasources,
    refreshLlmStatus,
    refreshSessions,
    renderDashboardArtifact,
    renderDashboardSpec,
    sanitizeEventPayload,
    setCurrentDatasource,
    updateComposerAvailability,
    subscribeToEvents,
    uploadDatasourceFile,
    saveGlobalLlmConfig,
    testLlmConfig,
    renameCurrentSession,
  };
})();
