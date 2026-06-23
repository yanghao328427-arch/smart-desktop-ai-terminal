App({
  globalData: {
    apiBase: "https://yh001399-smart-desktop-ai-terminal.hf.space",
    deviceId: "desktop-agent-001",
    refreshIntervalMs: 1500,
    controlToken: ""
  },
  onLaunch() {
    const apiBase = wx.getStorageSync("apiBase");
    if (apiBase) {
      this.globalData.apiBase = apiBase;
    }
    wx.removeStorageSync("controlToken");
    this.globalData.controlToken = "";
  }
});
