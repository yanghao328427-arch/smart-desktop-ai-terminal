const DEFAULT_API_BASE = "https://8-163-38-158.sslip.io";
const LEGACY_HF_API_BASE = "https://yh001399-smart-desktop-ai-terminal.hf.space";

App({
  globalData: {
    apiBase: DEFAULT_API_BASE,
    deviceId: "desktop-agent-001",
    refreshIntervalMs: 30000,
    controlToken: ""
  },
  onLaunch() {
    const apiBase = wx.getStorageSync("apiBase");
    if (apiBase === LEGACY_HF_API_BASE) {
      wx.setStorageSync("apiBase", DEFAULT_API_BASE);
    } else if (apiBase) {
      this.globalData.apiBase = apiBase;
    }
    wx.removeStorageSync("controlToken");
    this.globalData.controlToken = "";
  }
});
