(() => {
  async function apiGet(path) {
    const r = await fetch(path, { credentials: "same-origin" });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async function apiPost(path, body) {
    let r;
    try {
      r = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      const raw = String(e && e.message ? e.message : e);
      if (/failed to fetch/i.test(raw)) {
        throw new Error(
          "Сервер не ответил (Failed to fetch). Часто процесс упал — смотри терминал, перезапусти runtjsnew."
        );
      }
      throw e;
    }
    if (!r.ok) {
      let msg = await r.text();
      try {
        const j = JSON.parse(msg);
        msg = j.detail || j.error || msg;
      } catch (_) {}
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    const ct = r.headers.get("content-type") || "";
    if (ct.includes("application/json")) return r.json();
    return {};
  }

  window.pywebview = {
    api: {
      get_state: () => apiGet("/api/get_state"),
      poll_logs: async () => {
        const j = await apiGet("/api/poll_logs");
        if (j && Array.isArray(j.events)) return j.events;
        if (j && j.text) return j.text;
        return [];
      },
      check_adb: () => apiGet("/api/check_adb"),
      get_update_status: () => apiGet("/api/get_update_status"),
      apply_app_update: () => apiPost("/api/apply_app_update"),
      save_settings: (
        max_deals,
        min_amount,
        max_amount,
        allow_visa,
        allow_mastercard,
        max_empty_list_passes,
        from_pending,
        pipeline_bin_prefixes
      ) =>
        apiPost("/api/save_settings", {
          max_deals,
          min_amount,
          max_amount,
          allow_visa,
          allow_mastercard,
          max_empty_list_passes,
          from_pending: !!from_pending,
          pipeline_bin_prefixes: Array.isArray(pipeline_bin_prefixes)
            ? pipeline_bin_prefixes
            : [],
        }),
      save_redirect_filters: (skip_bog, visa_only, max_remaining, redirect_prefixes) =>
        apiPost("/api/save_redirect_filters", {
          skip_bog: !!skip_bog,
          visa_only: !!visa_only,
          max_remaining: !!max_remaining,
          redirect_prefixes: Array.isArray(redirect_prefixes)
            ? redirect_prefixes
            : [],
        }),
      start_pipeline: (
        max_deals,
        min_amount,
        max_amount,
        allow_visa,
        allow_mastercard,
        max_empty_list_passes,
        from_pending,
        pipeline_bin_prefixes
      ) =>
        apiPost("/api/start_pipeline", {
          max_deals,
          min_amount,
          max_amount,
          allow_visa,
          allow_mastercard,
          max_empty_list_passes,
          from_pending: !!from_pending,
          pipeline_bin_prefixes: Array.isArray(pipeline_bin_prefixes)
            ? pipeline_bin_prefixes
            : [],
        }),
      start_login: () => apiPost("/api/start_login"),
      start_accept_names: (max_deals, min_amount, max_amount) =>
        apiPost("/api/start_accept_names", {
          max_deals,
          min_amount: min_amount ?? null,
          max_amount: max_amount ?? null,
        }),
      stop_job: () => apiPost("/api/stop_job"),
      confirm: (kind) => apiPost("/api/confirm", { kind: kind || "receipts" }),
      cancel_completion_deal: (order_id) =>
        apiPost("/api/cancel_completion_deal", { order_id }),
      retry_completion_deal: (order_id) =>
        apiPost("/api/retry_completion_deal", { order_id }),
      rescan_completion_deal: (order_id) =>
        apiPost("/api/rescan_completion_deal", { order_id }),
      preview_receipts: () => apiGet("/api/preview_receipts"),
      recovery_retry: () => apiPost("/api/recovery_retry"),
      recovery_continue: () => apiPost("/api/recovery_continue"),
      recovery_exit: () => apiPost("/api/recovery_exit"),
      open_videos_folder: () => apiPost("/api/open_videos_folder"),
      open_screens_folder: () => apiPost("/api/open_screens_folder"),
      start_decline: (prefixes, tbc, max_per_run, min_amount, max_amount) =>
        apiPost("/api/start_decline", {
          prefixes: Array.isArray(prefixes) ? prefixes : [],
          tbc: !!tbc,
          max_per_run: max_per_run,
          min_amount: min_amount ?? null,
          max_amount: max_amount ?? null,
        }),
      start_redirect: (
        trader_ids,
        max_per_run,
        min_amount,
        max_amount,
        deal_status,
        skip_bog,
        visa_only,
        max_remaining,
        redirect_prefixes
      ) =>
        apiPost("/api/start_redirect", {
          trader_ids,
          max_per_run,
          min_amount,
          max_amount,
          deal_status: deal_status || "new",
          skip_bog: !!skip_bog,
          visa_only: !!visa_only,
          max_remaining: !!max_remaining,
          redirect_prefixes: Array.isArray(redirect_prefixes)
            ? redirect_prefixes
            : [],
        }),
    },
  };

  /* ── Status bar: legacy UI only (React dock owns controls) ── */
  function ensureControls() {
    const isLegacy = !!document.getElementById("status-bar");
    if (!isLegacy) {
      const leftover = document.getElementById("browser-server-bar");
      if (leftover) leftover.remove();
      return;
    }

    let bar = document.getElementById("browser-server-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "browser-server-bar";
      bar.className = "browser-server-bar";
      bar.setAttribute("role", "group");
      bar.setAttribute("aria-label", "Управление движком");
      bar.innerHTML = `
        <span class="srv-state" id="srv-state" hidden aria-hidden="true"></span>
        <span class="srv-power">
          <button type="button" id="btn-app-update" class="cmd-btn" title="Обновить код">↓</button>
          <button type="button" id="btn-srv-restart" class="cmd-btn" title="Перезапустить">↻</button>
          <button type="button" id="btn-srv-exit" class="cmd-btn" title="Выключить">⏻</button>
        </span>
      `;
      const statusBar = document.getElementById("status-bar");
      const cluster = statusBar && statusBar.querySelector(".status-actions");
      if (cluster) {
        const actions = cluster.querySelector(".cmd-actions");
        if (actions) cluster.insertBefore(bar, actions);
        else cluster.appendChild(bar);
      } else if (statusBar) {
        statusBar.appendChild(bar);
      }
    }

    bar.hidden = false;
    bar.style.removeProperty("display");

    ["btn-srv-start", "btn-srv-stop"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    });

    if (!document.getElementById("btn-srv-exit")) {
      const power = bar.querySelector(".srv-power") || bar;
      const exitBtn = document.createElement("button");
      exitBtn.type = "button";
      exitBtn.id = "btn-srv-exit";
      exitBtn.className = "cmd-btn";
      exitBtn.title = "Выключить";
      exitBtn.textContent = "⏻";
      power.appendChild(exitBtn);
    }

    const stateEl = document.getElementById("srv-state");
    if (stateEl) {
      stateEl.hidden = true;
      stateEl.setAttribute("aria-hidden", "true");
      stateEl.textContent = "";
    }

    const btnRestart = document.getElementById("btn-srv-restart");
    const btnExit = document.getElementById("btn-srv-exit");
    if (!btnRestart) return;

    async function refreshStatus() {
      try {
        const s = await apiGet("/api/server/status");
        btnRestart.disabled = !!s.restarting;
        if (btnExit) btnExit.disabled = !!s.restarting;
        if (stateEl) {
          stateEl.className = s.restarting
            ? "srv-state restarting"
            : s.engine_on
              ? "srv-state on"
              : "srv-state off";
        }
      } catch (_) {}
    }

    btnRestart.onclick = async () => {
      btnRestart.disabled = true;
      if (typeof window.clearCancelAlerts === "function") {
        window.clearCancelAlerts();
      }
      if (typeof appendLog === "function") appendLog("\n[SERVER] Перезапуск движка…\n");
      const r = await apiPost("/api/server/restart");
      await refreshStatus();
      if (r && r.ok === false && r.error) {
        if (typeof appendLog === "function") appendLog("[SERVER] Ошибка: " + r.error + "\n");
        return;
      }
      if (typeof appendLog === "function") appendLog("[SERVER] Перезапущено\n");
      if (typeof applyState === "function") {
        try {
          applyState(await window.pywebview.api.get_state());
        } catch (_) {}
      }
      if (typeof setStatus === "function") setStatus("Перезапущено — можно работать", "idle");
    };

    if (btnExit) {
      btnExit.onclick = async () => {
        let ok = true;
        if (typeof showConfirm === "function") {
          ok = await showConfirm(
            "Выключить Tzk полностью?\nСервер остановится, страница перестанет отвечать.",
            {
              title: "Выключение",
              confirmLabel: "Выключить",
              cancelLabel: "Назад",
              danger: true,
            }
          );
        } else {
          ok = window.confirm("Выключить Tzk полностью?");
        }
        if (!ok) return;
        btnExit.disabled = true;
        btnRestart.disabled = true;
        if (typeof appendLog === "function") appendLog("\n[SERVER] Выключение…\n");
        if (typeof setStatus === "function") setStatus("Выключение…", "idle");
        try {
          await apiPost("/api/server/shutdown");
        } catch (_) {}
        setTimeout(() => {
          if (typeof setStatus === "function") {
            setStatus("Сервер выключен — запусти start.sh снова", "error");
          }
        }, 600);
      };
    }

    refreshStatus();
    setInterval(refreshStatus, 2000);
  }

  let wsRetryMs = 800;
  function connectWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(proto + "//" + location.host + "/ws");
    ws.onopen = () => { wsRetryMs = 800; };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.type === "eval" && msg.script) {
        try { (0, eval)(msg.script); } catch (err) { console.warn("UI eval error", err, msg.script); }
      } else if (msg.type === "log") {
        if (Array.isArray(msg.events) && typeof ingestLogEvents === "function") {
          ingestLogEvents(msg.events);
        } else if (msg.text && typeof appendLog === "function") {
          appendLog(msg.text);
        }
      }
    };
    ws.onclose = () => {
      setTimeout(connectWs, wsRetryMs);
      wsRetryMs = Math.min(Math.round(wsRetryMs * 1.6), 8000);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  let booted = false;
  function boot() {
    if (booted) return;
    booted = true;
    ensureControls();
    connectWs();
    setTimeout(() => window.dispatchEvent(new Event("pywebviewready")), 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
