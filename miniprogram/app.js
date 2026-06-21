App({
  globalData: {
    apiBase: "https://yh001399-smart-desktop-ai-terminal.hf.space",
    deviceId: "desktop-agent-001",
    refreshIntervalMs: 1500,
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
