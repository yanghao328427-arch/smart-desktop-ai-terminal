const app = getApp();
const AUTO_REFRESH_MS = app.globalData.refreshIntervalMs || 5000;
const DEFAULT_SUMMARY = {
  protocolText: "-",
  aiText: "-",
  readyText: "等待真实接口",
  readyScore: "未检查",
  readyClass: "ready wait",
  readyCloudText: "-",
  readyDeviceText: "-",
  readyAckText: "-",
  readyQueueText: "-",
  connectionText: "0",
  onlineText: "离线",
  sessionText: "未连接",
  uartText: "未确认",
  ackText: "0/0",
  modeText: "-",
  userText: "-",
  pendingText: "0",
  voiceText: "-",
  temperatureText: "-",
  humidityText: "-",
  distanceText: "-",
  potText: "-",
  ntcText: "-",
  trackingText: "-",
  distanceZoneText: "-",
  envStateText: "-",
  interactionText: "-",
  rgbStatusText: "-",
  encoderText: "-",
  encoderButtonText: "-",
  lastSeenText: "-",
  lastAckText: "-",
  lastRfidText: "-",
  lastRfidAtText: "-",
  lastAsrText: "-",
  lastAsrAtText: "-",
  lastAsrStatusText: "-",
  lastAudioText: "-",
  speechText: "-",
  assistantText: "-",
  lastTextText: "-"
};

const VIEW_TITLES = {
  home: "智能桌面 AI 终端",
  overview: "链路总览",
  security: "安全设置",
  control: "硬件控制",
  sensors: "传感器",
  chat: "AI 对话",
  rfid: "RFID",
  actions: "动作记录",
  diagnostics: "后台日志"
};

function normalizeApiBase(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function buildWebSocketUrl(apiBase, deviceId) {
  const base = normalizeApiBase(apiBase);
  if (!base) return "";
  const wsBase = base.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://");
  if (!/^wss?:\/\//.test(wsBase)) return "";
  return `${wsBase}/api/realtime/ws?device_id=${encodeURIComponent(deviceId)}`;
}

function normalizeUid(value) {
  return String(value || "").trim().toUpperCase().replace(/[\s:-]+/g, "");
}

function formatTime(value) {
  if (!value) return "-";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (input) => String(input).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function shortActionId(value) {
  if (!value) return "-";
  return String(value).length > 18 ? `${String(value).slice(0, 18)}...` : String(value);
}

function formatSensorValue(value, unit = "") {
  if (value === undefined || value === null || value === "") return "-";
  return `${value}${unit}`;
}

function buildSummary(state, status, health) {
  const safeState = state || {};
  const safeStatus = status || {};
  const safeHealth = health || {};
  const sensors = safeState.sensors || {};
  const currentUser = safeState.current_user;
  const lastRfidUid = sensors.last_rfid_uid;
  const lastRfidAuthorized = sensors.last_rfid_authorized;
  const lastAudioPath = sensors.last_audio_path || "";
  const lastAudioName = lastAudioPath ? String(lastAudioPath).split(/[\\/]/).pop() : "-";
  const cloudOk = safeHealth.cloud_ready === true;
  const deviceOnline = safeState.online === true;
  const directWebSocket = safeState.session_connected === true;
  const deviceOk = deviceOnline && safeState.uart_ok;
  const lastAck = safeState.last_ack;
  const ackOk = Boolean(lastAck && lastAck.ok === true);
  const ackClean = (safeState.ack_err_count || 0) === 0;
  const queueOk = (safeState.pending_action_count || 0) === 0;
  const encoderOk = sensors.encoder_position !== undefined;
  const sensorOk = sensors.aht20_ok === true || sensors.pot_raw !== undefined || encoderOk;
  const ready = cloudOk && deviceOk && ackOk && ackClean && queueOk && sensorOk;
  const waiting = cloudOk && safeState.online && ackClean && queueOk && !ready;
  const attentionOnly = cloudOk && deviceOnline && safeState.uart_ok && ackClean;
  const readyScore = ready
    ? "运行正常"
    : (!cloudOk
      ? "云端未就绪"
      : (!deviceOnline
        ? "设备离线"
        : (!safeState.uart_ok
          ? "UART 待确认"
          : (!queueOk
            ? "待 ACK"
            : (!lastAck
              ? "待动作验证"
              : (!sensorOk ? "等待传感器" : "待确认"))))));

  return {
    protocolText: safeStatus.protocol || "-",
    aiText: cloudOk ? `${safeHealth.ai_provider}/${safeHealth.ai_model}` : "本地规则",
    readyText: `云端 ${cloudOk ? "OK" : "未就绪"} · 设备 ${deviceOnline ? (directWebSocket ? "WS 在线" : "HTTP 上报在线") : "未连接"} · UART ${safeState.uart_ok ? "OK" : "未确认"} · ACK ${lastAck ? (ackOk ? "OK" : "异常") : "待验证"} · 传感器 ${sensorOk ? "有上报" : "等待上报"}`,
    readyScore,
    readyClass: ready ? "ready ok" : (attentionOnly ? "ready warn" : "ready bad"),
    readyCloudText: cloudOk ? (safeHealth.ai_model || "OK") : "未就绪",
    readyDeviceText: deviceOk ? `${directWebSocket ? "WebSocket" : "HTTP 轮询"} / UART OK` : "检查连接",
    readyAckText: !lastAck ? "等待真实 ACK" : (ackOk ? `${safeState.ack_ok_count || 0} 个成功` : `${safeState.ack_err_count || 0} 个错误`),
    readyQueueText: queueOk ? "无待执行" : `${safeState.pending_action_count || 0} 个待 ACK`,
    connectionText: String(safeStatus.connection_count || 0),
    onlineText: safeState.online ? "在线" : "离线",
    sessionText: directWebSocket ? "WebSocket" : (deviceOnline ? "HTTP 轮询" : "未连接"),
    uartText: safeState.uart_ok ? "OK" : "未确认",
    ackText: `${safeState.ack_ok_count || 0}/${safeState.ack_err_count || 0}`,
    modeText: safeState.mode || "-",
    userText: currentUser ? `${currentUser.name}/${currentUser.mode}` : "-",
    pendingText: String(safeState.pending_action_count || 0),
    voiceText: safeState.voice_state || "-",
    temperatureText: sensors.aht20_ok ? formatSensorValue(sensors.temperature_c, " C") : "-",
    humidityText: sensors.aht20_ok ? formatSensorValue(sensors.humidity_pct, " %") : "-",
    distanceText: sensors.distance_ok ? formatSensorValue(sensors.distance_cm, " cm") : (sensors.distance_enabled === false ? "未启用" : "-"),
    potText: sensors.pot_raw !== undefined ? `${sensors.pot_raw}${sensors.pot_pct === undefined ? "" : ` / ${sensors.pot_pct}%`}` : "-",
    ntcText: sensors.ntc_raw !== undefined ? `${sensors.ntc_raw}${sensors.ntc_pct === undefined ? "" : ` / ${sensors.ntc_pct}%`}` : "-",
    trackingText: sensors.tracking_signal === undefined ? "-" : (sensors.tracking_signal ? "高" : "低"),
    distanceZoneText: sensors.distance_zone || "-",
    envStateText: sensors.env_state || "-",
    interactionText: sensors.interaction_hint || "-",
    rgbStatusText: sensors.rgb_status ? `${sensors.rgb_status}${sensors.rgb_reason ? ` / ${sensors.rgb_reason}` : ""}` : "-",
    encoderText: encoderOk ? `${sensors.encoder_position} (${sensors.encoder_delta >= 0 ? "+" : ""}${sensors.encoder_delta ?? 0})` : "-",
    encoderButtonText: sensors.encoder_button === undefined ? "-" : (sensors.encoder_button ? "按下" : "未按"),
    lastSeenText: formatTime(safeState.last_seen),
    lastAckText: lastAck ? `${lastAck.ok ? "OK" : "ERR"} ${shortActionId(lastAck.action_id)}` : "-",
    lastRfidText: lastRfidUid ? `${lastRfidUid} ${lastRfidAuthorized ? "通过" : "拒绝"}` : "-",
    lastRfidAtText: formatTime(sensors.last_rfid_at),
    lastAsrText: safeState.last_asr_text || "-",
    lastAsrAtText: formatTime(sensors.last_asr_at),
    lastAsrStatusText: sensors.last_asr_provider ? (sensors.last_asr_ok ? `成功 / ${sensors.last_asr_provider}` : `失败 / ${sensors.last_asr_provider}`) : "-",
    lastAudioText: lastAudioName,
    speechText: safeState.last_speech || "-",
    assistantText: safeState.last_assistant || "-",
    lastTextText: safeState.last_text || safeState.last_asr_text || "-"
  };
}

function buildStatusItems(state, status, health, summary) {
  const safeState = state || {};
  const safeHealth = health || {};
  const sensors = safeState.sensors || {};
  const cloudOk = safeHealth.cloud_ready === true;
  const online = safeState.online === true;
  const uartOk = safeState.uart_ok === true;
  const ackOk = Boolean(safeState.last_ack && safeState.last_ack.ok === true);
  const sensorOk = sensors.aht20_ok === true || sensors.pot_raw !== undefined || sensors.encoder_position !== undefined;
  return [
    {
      label: "云端 AI",
      value: cloudOk ? (safeHealth.ai_model || "OK") : "未就绪",
      note: cloudOk ? (safeHealth.ai_provider || "DashScope") : "检查 Hugging Face Secret",
      tone: cloudOk ? "ok" : "bad"
    },
    {
      label: "设备链路",
      value: online ? summary.sessionText : "离线",
      note: online ? `最近上报 ${summary.lastSeenText}` : "等待 ESP32 心跳",
      tone: online ? "ok" : "bad"
    },
    {
      label: "STM32 UART",
      value: uartOk ? "OK" : "未确认",
      note: uartOk ? "ESP32 到 STM32 正常" : "检查串口桥接",
      tone: uartOk ? "ok" : "warn"
    },
    {
      label: "动作 ACK",
      value: safeState.last_ack ? (ackOk ? "OK" : "异常") : "待验证",
      note: safeState.last_ack ? summary.lastAckText : "尚无真实动作回执",
      tone: safeState.last_ack ? (ackOk ? "ok" : "bad") : "warn"
    },
    {
      label: "传感器",
      value: sensorOk ? "有上报" : "等待",
      note: `${summary.temperatureText} · ${summary.humidityText} · ${summary.distanceText}`,
      tone: sensorOk ? "ok" : "warn"
    },
    {
      label: "执行队列",
      value: summary.readyQueueText,
      note: `连接数 ${status && status.connection_count ? status.connection_count : 0}`,
      tone: (safeState.pending_action_count || 0) === 0 ? "ok" : "warn"
    }
  ];
}

function describeRecentAction(action) {
  const statusMap = {
    queued: "待发送",
    sent: "已发送",
    acked: "ACK OK",
    failed: "ACK ERR"
  };
  return {
    id: action.id,
    title: `${statusMap[action.status] || action.status} · ${action.type}`,
    line: action.status === "failed" ? (action.error || "执行异常") : "命令已提交到设备链路",
    time: formatTime(action.acked_at || action.sent_at || action.created_at)
  };
}

Page({
  data: {
    apiBase: normalizeApiBase(app.globalData.apiBase),
    controlToken: "",
    deviceId: app.globalData.deviceId,
    state: {},
    status: {},
    chatText: "",
    messages: [],
    rfid: {
      uid: "",
      userId: "",
      name: "",
      profileSummary: "",
      adminNotes: "",
      enrollId: "",
      enrollStatus: "未开始"
    },
    modes: ["study", "rest", "admin"],
    modeIndex: 0,
    diagnosticsText: "{}",
    summary: DEFAULT_SUMMARY,
    statusItems: buildStatusItems({}, {}, {}, DEFAULT_SUMMARY),
    recentActions: [],
    refreshTime: "-",
    socketText: "WS 未连接",
    currentView: "home",
    currentTitle: VIEW_TITLES.home,
    controlTokenDraft: "",
    tokenSaved: false,
    tokenSavedText: "本次未输入"
  },

  onLoad() {
    this.refreshState();
  },

  onShow() {
    this.socketWanted = true;
    this.connectRealtimeSocket();
    this.startAutoRefresh();
    this.refreshState({ quiet: true });
  },

  onHide() {
    this.socketWanted = false;
    this.closeRealtimeSocket();
    this.stopAutoRefresh();
    this.clearRfidEnrollTimer();
  },

  onUnload() {
    this.socketWanted = false;
    this.closeRealtimeSocket();
    this.stopAutoRefresh();
    this.clearRfidEnrollTimer();
  },

  onPullDownRefresh() {
    this.refreshState();
  },

  request(path, method = "GET", data = undefined) {
    return new Promise((resolve, reject) => {
      const apiBase = normalizeApiBase(this.data.apiBase);
      if (!apiBase) {
        reject(new Error("请先填写后端地址"));
        return;
      }
      wx.request({
        url: `${apiBase}${path}`,
        method,
        data,
        header: {
          "content-type": "application/json",
          ...(this.data.controlToken ? { "X-Demo-Token": this.data.controlToken } : {})
        },
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data);
          } else {
            reject(new Error(res.data && res.data.detail ? res.data.detail : `HTTP ${res.statusCode}`));
          }
        },
        fail: reject
      });
    });
  },

  toast(title) {
    wx.showToast({ title, icon: "none" });
  },

  setView(event) {
    const view = event.currentTarget.dataset.view || "home";
    this.setData({
      currentView: VIEW_TITLES[view] ? view : "home",
      currentTitle: VIEW_TITLES[view] || VIEW_TITLES.home
    });
  },

  ensureControlToken() {
    if (this.data.controlToken) return true;
    this.toast("先在安全设置输入本次控制口令");
    this.setData({
      currentView: "security",
      currentTitle: VIEW_TITLES.security
    });
    return false;
  },

  hasActiveUserContext() {
    const state = this.data.state || {};
    const sensors = state.sensors || {};
    return Boolean(state.current_user && state.active_session_id && sensors.active_context_physical_card === true);
  },

  ensureAccessContext() {
    if (this.data.controlToken || this.hasActiveUserContext()) return true;
    this.toast("先刷已注册 RFID 卡或输入本次控制口令");
    this.setData({
      currentView: "rfid",
      currentTitle: VIEW_TITLES.rfid
    });
    return false;
  },

  appendMessage(role, text) {
    const messages = this.data.messages.concat([{ id: Date.now() + Math.random(), role, text }]);
    this.setData({ messages });
  },

  appendSystemNote(text) {
    this.appendMessage("assistant", text);
  },

  onApiBaseInput(event) {
    this.setData({ apiBase: event.detail.value.trim() });
  },

  saveApiBase() {
    const apiBase = normalizeApiBase(this.data.apiBase);
    if (!/^https?:\/\//.test(apiBase)) {
      this.toast("地址需以 http:// 或 https:// 开头");
      return;
    }
    this.setData({ apiBase });
    wx.setStorageSync("apiBase", apiBase);
    app.globalData.apiBase = apiBase;
    this.toast("已保存");
    this.closeRealtimeSocket();
    this.connectRealtimeSocket();
    this.refreshState();
  },


  onControlTokenInput(event) {
    this.setData({ controlTokenDraft: event.detail.value.trim() });
  },

  saveControlToken() {
    const controlToken = String(this.data.controlTokenDraft || "").trim();
    this.setData({
      controlToken,
      controlTokenDraft: "",
      tokenSaved: Boolean(controlToken),
      tokenSavedText: controlToken ? "本次有效" : "本次未输入"
    });
    wx.removeStorageSync("controlToken");
    app.globalData.controlToken = controlToken;
    this.toast(controlToken ? "控制口令本次有效" : "控制口令为空");
  },

  clearControlToken() {
    this.setData({
      controlToken: "",
      controlTokenDraft: "",
      tokenSaved: false,
      tokenSavedText: "本次未输入"
    });
    wx.removeStorageSync("controlToken");
    app.globalData.controlToken = "";
    this.toast("已清除本次口令");
  },
  onChatInput(event) {
    this.setData({ chatText: event.detail.value });
  },

  onRfidUidInput(event) {
    this.setData({ "rfid.uid": event.detail.value });
  },

  onRfidUserIdInput(event) {
    this.setData({ "rfid.userId": event.detail.value });
  },

  onRfidNameInput(event) {
    this.setData({ "rfid.name": event.detail.value });
  },

  onRfidSummaryInput(event) {
    this.setData({ "rfid.profileSummary": event.detail.value });
  },

  onRfidNotesInput(event) {
    this.setData({ "rfid.adminNotes": event.detail.value });
  },

  onModeChange(event) {
    this.setData({ modeIndex: Number(event.detail.value) });
  },

  startAutoRefresh() {
    if (this.refreshTimer) return;
    this.refreshTimer = setInterval(() => {
      this.refreshState({ quiet: true });
    }, AUTO_REFRESH_MS);
  },

  stopAutoRefresh() {
    if (!this.refreshTimer) return;
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  },

  clearRfidEnrollTimer() {
    if (!this.rfidEnrollTimer) return;
    clearTimeout(this.rfidEnrollTimer);
    this.rfidEnrollTimer = null;
  },

  connectRealtimeSocket() {
    if (this.socketTask || !this.socketWanted) return;
    const url = buildWebSocketUrl(this.data.apiBase, this.data.deviceId);
    if (!url) {
      this.setData({ socketText: "WS 地址无效" });
      return;
    }
    const task = wx.connectSocket({ url });
    this.socketTask = task;
    this.setData({ socketText: "WS 连接中" });

    task.onOpen(() => {
      this.socketReconnectDelayMs = 1000;
      this.setData({ socketText: "WS 已连接" });
    });

    task.onMessage((event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.state) {
          this.setData({ state: message.state });
        }
        this.queueRealtimeRefresh();
      } catch (error) {
        this.queueRealtimeRefresh();
      }
    });

    task.onError(() => {
      this.setData({ socketText: "WS 异常，轮询兜底" });
    });

    task.onClose(() => {
      if (this.socketTask && this.socketTask !== task) {
        return;
      }
      this.socketTask = null;
      this.setData({ socketText: this.socketWanted ? "WS 重连中" : "WS 已断开" });
      if (this.socketWanted) {
        this.scheduleSocketReconnect();
      }
    });
  },

  closeRealtimeSocket() {
    if (this.socketReconnectTimer) {
      clearTimeout(this.socketReconnectTimer);
      this.socketReconnectTimer = null;
    }
    if (!this.socketTask) {
      this.setData({ socketText: "WS 已断开" });
      return;
    }
    const task = this.socketTask;
    this.socketTask = null;
    task.close({ code: 1000, reason: "page hidden" });
    this.setData({ socketText: "WS 已断开" });
  },

  scheduleSocketReconnect() {
    if (this.socketReconnectTimer) return;
    const delay = this.socketReconnectDelayMs || 1000;
    this.socketReconnectDelayMs = Math.min(delay * 2, 15000);
    this.socketReconnectTimer = setTimeout(() => {
      this.socketReconnectTimer = null;
      this.connectRealtimeSocket();
    }, delay);
  },

  queueRealtimeRefresh() {
    if (this.realtimeRefreshTimer) return;
    this.realtimeRefreshTimer = setTimeout(() => {
      this.realtimeRefreshTimer = null;
      this.refreshState({ quiet: true });
    }, 150);
  },

  async refreshState(options = {}) {
    if (this.refreshing) return;
    this.refreshing = true;
    try {
      const [state, status, diagnostics, health] = await Promise.all([
        this.request(`/api/state/${this.data.deviceId}`),
        this.request("/api/realtime/status"),
        this.request(`/api/realtime/diagnostics/${this.data.deviceId}`),
        this.request("/api/health")
      ]);
      const summary = buildSummary(state, status, health);
      this.setData({
        state,
        status,
        diagnosticsText: JSON.stringify(diagnostics, null, 2),
        summary,
        statusItems: buildStatusItems(state, status, health, summary),
        recentActions: (diagnostics.recent_actions || []).slice().reverse().slice(0, 6).map(describeRecentAction),
        refreshTime: `最近刷新 ${formatTime(new Date())}`
      });
    } catch (error) {
      if (!options.quiet) {
        this.toast(error.message);
      }
    } finally {
      this.refreshing = false;
      wx.stopPullDownRefresh();
    }
  },

  async sendChatText(rawText) {
    const text = String(rawText || "").trim();
    if (!text) return;
    if (!this.ensureAccessContext()) return;
    this.setData({ chatText: "" });
    this.appendMessage("user", text);
    try {
      const response = await this.request("/api/chat", "POST", { device_id: this.data.deviceId, text });
      this.appendMessage("assistant", response.reply);
      if (response.actions && response.actions.length) this.appendSystemNote(`已生成 ${response.actions.length} 条设备动作，等待 ACK。`);
      this.setData({ state: response.state });
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },

  sendChat() {
    return this.sendChatText(this.data.chatText);
  },

  sendPreset(event) {
    this.sendChatText(event.currentTarget.dataset.text);
  },

  async sendHardwareAction(event) {
    if (!this.ensureAccessContext()) return;
    const actionMap = {
      fan_on: { label: "打开风扇", type: "fan_control", payload: { state: "on", level: 2 } },
      beep: { label: "蜂鸣提醒", type: "buzzer_alert", payload: {} },
      lock: { label: "锁定", type: "lock_control", payload: { state: "on" } },
      unlock: { label: "解锁", type: "lock_control", payload: { state: "off" } }
    };
    const spec = actionMap[event.currentTarget.dataset.tool];
    if (!spec) return;
    try {
      const response = await this.request("/api/hardware/action", "POST", {
        device_id: this.data.deviceId,
        type: spec.type,
        payload: spec.payload,
        mark_sent: true
      });
      this.setData({ state: response.state });
      this.appendSystemNote(`${spec.label}已提交，等待设备 ACK。`);
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },
  scheduleRfidEnrollmentPoll(enrollId) {
    this.clearRfidEnrollTimer();
    this.rfidEnrollTimer = setTimeout(() => {
      this.pollRfidEnrollment(enrollId);
    }, 1200);
  },

  async pollRfidEnrollment(enrollId) {
    if (!enrollId || enrollId !== this.data.rfid.enrollId) return;
    try {
      const response = await this.request(`/api/rfid/enroll/${enrollId}`);
      this.setData({
        "rfid.enrollStatus": response.status,
        state: response.state || this.data.state
      });
      if (response.status === "completed") {
        this.clearRfidEnrollTimer();
        this.appendMessage("assistant", `RFID 注册完成 ${response.uid} -> ${response.user.name}/${response.user.mode}`);
        this.refreshState({ quiet: true });
        return;
      }
      if (response.status === "pending") {
        this.scheduleRfidEnrollmentPoll(enrollId);
        return;
      }
      this.clearRfidEnrollTimer();
      this.appendMessage("assistant", `RFID 注册${response.status === "expired" ? "已过期" : "已取消"}`);
      this.refreshState({ quiet: true });
    } catch (error) {
      this.clearRfidEnrollTimer();
      this.toast(error.message);
    }
  },

  async startRfidEnrollment() {
    if (!this.ensureControlToken()) return;
    const userId = this.data.rfid.userId.trim();
    const name = this.data.rfid.name.trim();
    const payload = {
      device_id: this.data.deviceId,
      mode: this.data.modes[this.data.modeIndex],
      profile_summary: this.data.rfid.profileSummary.trim() || null,
      admin_notes: this.data.rfid.adminNotes.trim() || null
    };
    if (userId) {
      payload.user_id = userId;
    } else {
      payload.name = name || `user-${Date.now().toString().slice(-6)}`;
    }
    try {
      const response = await this.request("/api/rfid/enroll/start", "POST", payload);
      this.setData({
        "rfid.enrollId": response.enroll_id,
        "rfid.enrollStatus": response.status
      });
      this.appendMessage("assistant", `RFID 在线注册已开始 ${response.enroll_id.slice(0, 8)}`);
      this.scheduleRfidEnrollmentPoll(response.enroll_id);
    } catch (error) {
      this.toast(error.message);
    }
  },

  async registerRfid() {
    if (!this.ensureControlToken()) return;
    const uid = normalizeUid(this.data.rfid.uid);
    if (!uid) {
      this.toast("请先输入 UID");
      return;
    }
    try {
      const response = await this.request("/api/rfid/register", "POST", {
        device_id: this.data.deviceId,
        uid,
        name: this.data.rfid.name.trim() || uid,
        mode: this.data.modes[this.data.modeIndex],
        profile_summary: this.data.rfid.profileSummary.trim() || null,
        admin_notes: this.data.rfid.adminNotes.trim() || null
      });
      this.setData({ state: response.state });
      this.appendMessage(
        "assistant",
        `已绑定 ${response.user.uid} -> ${response.user.name}/${response.user.mode}`
      );
      this.toast("已绑定");
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },

  async scanRfid() {
    if (!this.ensureControlToken()) return;
    const uid = normalizeUid(this.data.rfid.uid);
    if (!uid) {
      this.toast("请先输入 UID");
      return;
    }
    try {
      const response = await this.request("/api/rfid/scan", "POST", {
        device_id: this.data.deviceId,
        uid,
        source: "web_simulator"
      });
      this.setData({ state: response.state });
      this.appendMessage("assistant", `${response.authorized ? "RFID OK" : "RFID DENY"} ${response.uid} · ${response.source}`);
      this.appendMessage("assistant", response.message);
      if (response.actions && response.actions.length) this.appendSystemNote(`RFID 已触发 ${response.actions.length} 条设备动作，等待 ACK。`);
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },

  manualRefresh() {
    this.refreshState();
  }
});
