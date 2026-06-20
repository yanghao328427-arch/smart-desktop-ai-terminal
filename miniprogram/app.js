App({
  globalData: {
    apiBase: "https://smart-desktop-ai-terminal.onrender.com",
    deviceId: "desktop-agent-001",
    refreshIntervalMs: 5000,
    controlToken: ""
  },
  onLaunch() {
    const apiBase = wx.getStorageSync("apiBase");
    const controlToken = wx.getStorageSync("controlToken");
    if (apiBase) {
      this.globalData.apiBase = apiBase;
    }
    if (controlToken) {
      this.globalData.controlToken = controlToken;
    }
  }
});
