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

function normalizeApiBase(value) {
  return String(value || "").trim().replace(/\/+$/, "");
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

  return {
    protocolText: safeStatus.protocol || "-",
    aiText: cloudOk ? `${safeHealth.ai_provider}/${safeHealth.ai_model}` : "本地规则",
    readyText: `云端 ${cloudOk ? "OK" : "未就绪"} · 设备 ${deviceOnline ? (directWebSocket ? "WS 在线" : "中继在线") : "未连接"} · UART ${safeState.uart_ok ? "OK" : "未确认"} · ACK ${lastAck ? (ackOk ? "OK" : "异常") : "待验证"} · 传感器 ${sensorOk ? "有上报" : "等待上报"}`,
    readyScore: ready ? "闭环就绪" : (waiting ? "待确认" : "需处理"),
    readyClass: ready ? "ready ok" : (waiting ? "ready warn" : "ready bad"),
    readyCloudText: cloudOk ? (safeHealth.ai_model || "OK") : "未就绪",
    readyDeviceText: deviceOk ? `${directWebSocket ? "WebSocket" : "中继轮询"} / UART OK` : "检查连接",
    readyAckText: !lastAck ? "等待真实 ACK" : (ackOk ? `${safeState.ack_ok_count || 0} 个成功` : `${safeState.ack_err_count || 0} 个错误`),
    readyQueueText: queueOk ? "无待执行" : `${safeState.pending_action_count || 0} 个待 ACK`,
    connectionText: String(safeStatus.connection_count || 0),
    onlineText: safeState.online ? "在线" : "离线",
    sessionText: directWebSocket ? "WebSocket" : (deviceOnline ? "中继轮询" : "未连接"),
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
    line: action.command,
    time: formatTime(action.acked_at || action.sent_at || action.created_at)
  };
}

Page({
  data: {
    apiBase: normalizeApiBase(app.globalData.apiBase),
    controlToken: app.globalData.controlToken || "",
    deviceId: app.globalData.deviceId,
    state: {},
    status: {},
    chatText: "",
    messages: [],
    rfid: { uid: "", name: "" },
    modes: ["study", "rest", "admin"],
    modeIndex: 0,
    diagnosticsText: "{}",
    summary: DEFAULT_SUMMARY,
    recentActions: [],
    refreshTime: "-"
  },

  onLoad() {
    this.refreshState();
  },

  onShow() {
    this.startAutoRefresh();
    this.refreshState({ quiet: true });
  },

  onHide() {
    this.stopAutoRefresh();
  },

  onUnload() {
    this.stopAutoRefresh();
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

  appendMessage(role, text) {
    const messages = this.data.messages.concat([{ id: Date.now() + Math.random(), role, text }]);
    this.setData({ messages });
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
    this.refreshState();
  },


  onControlTokenInput(event) {
    this.setData({ controlToken: event.detail.value.trim() });
  },

  saveControlToken() {
    const controlToken = String(this.data.controlToken || "").trim();
    this.setData({ controlToken });
    wx.setStorageSync("controlToken", controlToken);
    app.globalData.controlToken = controlToken;
    this.toast("控制口令已保存");
  },
  onChatInput(event) {
    this.setData({ chatText: event.detail.value });
  },

  onRfidUidInput(event) {
    this.setData({ "rfid.uid": event.detail.value });
  },

  onRfidNameInput(event) {
    this.setData({ "rfid.name": event.detail.value });
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
      this.setData({
        state,
        status,
        diagnosticsText: JSON.stringify(diagnostics, null, 2),
        summary: buildSummary(state, status, health),
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
    this.setData({ chatText: "" });
    this.appendMessage("user", text);
    try {
      const response = await this.request("/api/chat", "POST", { device_id: this.data.deviceId, text });
      this.appendMessage("assistant", response.reply);
      if (response.commands && response.commands.length) {
        this.appendMessage("assistant", response.commands.join("\n"));
      }
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
      this.appendMessage("assistant", `${spec.label}：${(response.commands || []).join(" / ") || "已入队"}`);
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },
  async registerRfid() {
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
        mode: this.data.modes[this.data.modeIndex]
      });
      this.setData({ state: response.state });
      this.appendMessage("assistant", `已注册 ${response.user.uid} -> ${response.user.name}/${response.user.mode}`);
      this.toast("已注册");
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },

  async scanRfid() {
    const uid = normalizeUid(this.data.rfid.uid);
    if (!uid) {
      this.toast("请先输入 UID");
      return;
    }
    try {
      const response = await this.request("/api/rfid/scan", "POST", { device_id: this.data.deviceId, uid });
      this.setData({ state: response.state });
      this.appendMessage("assistant", `${response.authorized ? "RFID OK" : "RFID DENY"} ${response.uid}`);
      this.appendMessage("assistant", response.message);
      if (response.commands && response.commands.length) {
        this.appendMessage("assistant", response.commands.join("\n"));
      }
      this.refreshState({ quiet: true });
    } catch (error) {
      this.toast(error.message);
    }
  },

  manualRefresh() {
    this.refreshState();
  }
});
