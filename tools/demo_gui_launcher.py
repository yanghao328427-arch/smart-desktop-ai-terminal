from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import urllib.error
import urllib.request
import webbrowser


BASE_URL = "https://8-163-38-158.sslip.io"
DIRECT_ESP32_SERVER = "http://8.163.38.158"
DEVICE_ID = "desktop-agent-001"
MAX_AGE_SECONDS = 20.0
READY_WAIT_SECONDS = 180
SERIAL_BAUD = 115200
SERIAL_OPEN_DELAY_SECONDS = 8.0
SENSOR_KEYS = (
    "temperature_c",
    "humidity_pct",
    "distance_cm",
    "pot_raw",
    "ntc_raw",
    "tracking_signal",
    "encoder_position",
)


def package_root() -> Path:
    override = os.environ.get("SMARTDESK_DEMO_PACKAGE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_path(*parts: str) -> Path:
    return package_root().joinpath(*parts)


def request_json(url: str, timeout: int = 8) -> dict:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "SmartDesk-Defense-GUI/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def age_seconds(value: object) -> float | None:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())


def readiness_snapshot() -> dict:
    health = request_json(f"{BASE_URL}/api/health")
    state = request_json(f"{BASE_URL}/api/state/{DEVICE_ID}")
    diagnostics = request_json(f"{BASE_URL}/api/realtime/diagnostics/{DEVICE_ID}")
    diagnostic_state = diagnostics.get("state") if isinstance(diagnostics, dict) else {}
    if not isinstance(diagnostic_state, dict):
        diagnostic_state = {}

    state_age = age_seconds(state.get("last_seen"))
    diagnostics_age = age_seconds(diagnostic_state.get("last_seen"))
    sensors = state.get("sensors") if isinstance(state.get("sensors"), dict) else {}
    present_sensors = [key for key in SENSOR_KEYS if sensors.get(key) is not None]
    checks = {
        "cloud": health.get("cloud_ready") is True,
        "storage": health.get("persistent_storage") is True,
        "device": state.get("online") is True,
        "websocket": state.get("session_connected") is True,
        "uart": state.get("uart_ok") is True,
        "ack": state.get("ack_err_count", 0) == 0,
        "queue": state.get("pending_action_count", 0) == 0,
        "state_fresh": state_age is not None and state_age <= MAX_AGE_SECONDS,
        "diagnostics_fresh": diagnostics_age is not None
        and diagnostics_age <= MAX_AGE_SECONDS,
        "sensors": len(present_sensors) >= 2,
        "edge": bool(state.get("edge_id"))
        and state.get("edge_id") == diagnostic_state.get("edge_id"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not failed,
        "checks": checks,
        "failed": failed,
        "state_age": state_age,
        "diagnostics_age": diagnostics_age,
        "sensor_count": len(present_sensors),
        "ack_ok_count": state.get("ack_ok_count", 0),
        "ack_err_count": state.get("ack_err_count", 0),
        "pending_action_count": state.get("pending_action_count", 0),
    }


def open_local_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    os.startfile(path)  # type: ignore[attr-defined]


def hidden_process_flags() -> tuple[int, subprocess.STARTUPINFO | None]:
    if os.name != "nt":
        return 0, None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return subprocess.CREATE_NO_WINDOW, startup


def run_hidden_command(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    creationflags, startupinfo = hidden_process_flags()
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )


def parse_wifi_interface(output: str) -> tuple[str, str]:
    interface_name = ""
    ssid = ""
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized = key.strip().casefold()
        clean_value = value.strip()
        if normalized in {"name", "名称"} and not interface_name:
            interface_name = clean_value
        elif normalized == "ssid" and clean_value:
            ssid = clean_value
    return interface_name, ssid


def parse_wifi_password(output: str) -> str:
    accepted_keys = {
        "key content",
        "关键内容",
        "密钥内容",
    }
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        if key.strip().casefold() in accepted_keys:
            return value.strip()
    return ""


def valid_lan_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return (
        isinstance(address, ipaddress.IPv4Address)
        and address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address in ipaddress.ip_network("198.18.0.0/15")
    )


def detect_current_network() -> dict[str, str]:
    interfaces = run_hidden_command(["netsh", "wlan", "show", "interfaces"])
    if interfaces.returncode != 0:
        raise RuntimeError((interfaces.stderr or interfaces.stdout or "无法读取 WLAN 状态").strip())
    interface_name, ssid = parse_wifi_interface(interfaces.stdout)
    if not ssid:
        raise RuntimeError("当前没有连接到 Wi-Fi。")

    ip_value = ""
    if interface_name:
        escaped_alias = interface_name.replace("'", "''")
        script = (
            f"Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias '{escaped_alias}' "
            "-ErrorAction SilentlyContinue | "
            "Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -ne '127.0.0.1' } | "
            "Select-Object -ExpandProperty IPAddress -First 1"
        )
        ip_result = run_hidden_command(
            ["powershell", "-NoProfile", "-Command", script],
            timeout=20,
        )
        candidate = ip_result.stdout.strip().splitlines()
        if candidate and valid_lan_ipv4(candidate[0]):
            ip_value = candidate[0].strip()
    if not ip_value:
        raise RuntimeError(f"已识别 Wi-Fi“{ssid}”，但没有找到可用的物理 WLAN IPv4。")
    return {"interface": interface_name, "ssid": ssid, "ip": ip_value}


def read_saved_wifi_password(ssid: str) -> str:
    result = run_hidden_command(
        ["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"],
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError("Windows 无法读取该 Wi-Fi 的已保存配置。")
    password = parse_wifi_password(result.stdout)
    if not password:
        raise RuntimeError("该 Wi-Fi 没有可读取的已保存密码，请手动输入。")
    return password


def stop_existing_voice_listeners() -> list[dict[str, object]]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq '语音监听器.exe' -and "
        "($_.CommandLine -like '*desktop-agent-001*' -or $_.ExecutablePath -like '*智能桌面AI终端*') } | "
        "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    )
    result = run_hidden_command(
        ["powershell", "-NoProfile", "-Command", script],
        timeout=20,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    decoded = json.loads(result.stdout)
    processes = decoded if isinstance(decoded, list) else [decoded]
    stopped: list[dict[str, object]] = []
    for process in processes:
        pid = int(process.get("ProcessId") or 0)
        if pid <= 0:
            continue
        taskkill = run_hidden_command(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            timeout=10,
        )
        if taskkill.returncode == 0:
            stopped.append(process)
    return stopped


class DemoLauncher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("智能桌面 AI 终端｜答辩演示启动器")
        self.root.geometry("980x820")
        self.root.minsize(920, 740)
        self.root.configure(bg="#f6f6f6")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.listener: subprocess.Popen[str] | None = None
        self.busy = False

        self.status_var = tk.StringVar(value="准备就绪")
        self.cloud_var = tk.StringVar(value="待检查")
        self.device_var = tk.StringVar(value="待检查")
        self.uart_var = tk.StringVar(value="待检查")
        self.sensor_var = tk.StringVar(value="待检查")
        self.listener_var = tk.StringVar(value="未启动")
        self.input_device_var = tk.StringVar(value="1")
        self.wifi_ssid_var = tk.StringVar(value="待检测")
        self.lan_ip_var = tk.StringVar(value="待检测")
        self.wifi_password_var = tk.StringVar(value="")
        self.serial_port_var = tk.StringVar(value="COM8")
        self.esp32_server_var = tk.StringVar(value=DIRECT_ESP32_SERVER)
        self.show_wifi_password_var = tk.BooleanVar(value=False)

        self.build_ui()
        self.root.after(100, self.drain_events)
        self.log("双击启动器后，所有状态都会在这里显示，不需要使用命令行。")
        self.run_async(self.check_once)
        self.run_async(self.detect_network_worker)

    def build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#111111", height=102)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="智能桌面 AI 终端",
            bg="#111111",
            fg="white",
            font=("Microsoft YaHei UI", 24, "bold"),
        ).pack(anchor="w", padx=30, pady=(18, 0))
        tk.Label(
            header,
            text="答辩演示启动器｜实时检查 · 网页控制台 · 关键词监听",
            bg="#111111",
            fg="#ff7a45",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=31, pady=(4, 0))

        body = tk.Frame(self.root, bg="#f6f6f6")
        body.pack(fill="both", expand=True, padx=28, pady=20)

        state_frame = tk.Frame(body, bg="#f6f6f6")
        state_frame.pack(fill="x")
        status_items = (
            ("云端模型", self.cloud_var),
            ("设备在线", self.device_var),
            ("STM32 UART", self.uart_var),
            ("真实传感器", self.sensor_var),
            ("语音监听", self.listener_var),
        )
        for index, (title, variable) in enumerate(status_items):
            card = tk.Frame(state_frame, bg="#ededed", width=154, height=76)
            card.grid(row=0, column=index, padx=(0, 10 if index < 4 else 0), sticky="nsew")
            card.grid_propagate(False)
            tk.Label(
                card,
                text=title,
                bg="#ededed",
                fg="#555555",
                font=("Microsoft YaHei UI", 9),
            ).pack(anchor="w", padx=14, pady=(12, 2))
            tk.Label(
                card,
                textvariable=variable,
                bg="#ededed",
                fg="#111111",
                font=("Microsoft YaHei UI", 11, "bold"),
            ).pack(anchor="w", padx=14)
            state_frame.grid_columnconfigure(index, weight=1)

        main_actions = tk.Frame(body, bg="#f6f6f6")
        main_actions.pack(fill="x", pady=(18, 10))
        self.start_button = tk.Button(
            main_actions,
            text="一键启动完整演示",
            command=self.start_full_demo,
            bg="#ff6b35",
            fg="white",
            activebackground="#e85b2a",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 14, "bold"),
            height=2,
        )
        self.start_button.pack(side="left", fill="x", expand=True)
        self.stop_button = tk.Button(
            main_actions,
            text="停止语音监听",
            command=self.stop_listener,
            bg="#dedede",
            fg="#222222",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 11, "bold"),
            width=18,
            state="disabled",
        )
        self.stop_button.pack(side="left", fill="y", padx=(12, 0))

        secondary = tk.Frame(body, bg="#f6f6f6")
        secondary.pack(fill="x", pady=(0, 14))
        for text, command in (
            ("重新检查设备", lambda: self.run_async(self.check_once)),
            ("仅打开网页", self.open_console),
            ("查看演示讲稿", self.open_script),
            ("打开答辩 PPT", self.open_ppt),
            ("查看麦克风", self.show_audio_devices),
        ):
            tk.Button(
                secondary,
                text=text,
                command=command,
                bg="#e7e7e7",
                fg="#222222",
                activebackground="#d9d9d9",
                relief="flat",
                cursor="hand2",
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=12,
                pady=8,
            ).pack(side="left", padx=(0, 8))

        settings = tk.Frame(body, bg="#f6f6f6")
        settings.pack(fill="x", pady=(0, 10))
        tk.Label(
            settings,
            text="麦克风编号",
            bg="#f6f6f6",
            fg="#555555",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        ttk.Entry(settings, textvariable=self.input_device_var, width=7).pack(
            side="left", padx=(8, 14)
        )
        tk.Label(
            settings,
            textvariable=self.status_var,
            bg="#f6f6f6",
            fg="#ff6b35",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")

        network = tk.LabelFrame(
            body,
            text="现场网络与 ESP32 配置",
            bg="#f6f6f6",
            fg="#333333",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=10,
        )
        network.pack(fill="x", pady=(0, 12))
        tk.Label(network, text="Wi-Fi", bg="#f6f6f6", fg="#555555").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(network, textvariable=self.wifi_ssid_var, width=24, state="readonly").grid(
            row=0, column=1, padx=(6, 12), sticky="ew"
        )
        tk.Label(network, text="本机 IPv4", bg="#f6f6f6", fg="#555555").grid(
            row=0, column=2, sticky="w"
        )
        ttk.Entry(network, textvariable=self.lan_ip_var, width=16, state="readonly").grid(
            row=0, column=3, padx=(6, 12), sticky="ew"
        )
        tk.Button(
            network,
            text="检测当前网络",
            command=lambda: self.run_async(self.detect_network_worker),
            bg="#e7e7e7",
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=5,
        ).grid(row=0, column=4, sticky="ew")

        tk.Label(network, text="Wi-Fi 密钥", bg="#f6f6f6", fg="#555555").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.wifi_password_entry = ttk.Entry(
            network,
            textvariable=self.wifi_password_var,
            width=24,
            show="*",
        )
        self.wifi_password_entry.grid(
            row=1, column=1, padx=(6, 12), pady=(8, 0), sticky="ew"
        )
        tk.Checkbutton(
            network,
            text="显示",
            variable=self.show_wifi_password_var,
            command=self.toggle_wifi_password,
            bg="#f6f6f6",
            activebackground="#f6f6f6",
        ).grid(row=1, column=2, sticky="w", pady=(8, 0))
        tk.Button(
            network,
            text="读取 Windows 已保存密钥",
            command=lambda: self.run_async(self.read_wifi_password_worker),
            bg="#e7e7e7",
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=5,
        ).grid(row=1, column=3, columnspan=2, pady=(8, 0), sticky="ew")

        tk.Label(network, text="ESP32 服务地址", bg="#f6f6f6", fg="#555555").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(network, textvariable=self.esp32_server_var, width=24).grid(
            row=2, column=1, padx=(6, 12), pady=(8, 0), sticky="ew"
        )
        tk.Button(
            network,
            text="阿里云直连",
            command=self.use_direct_server,
            bg="#e7e7e7",
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=5,
        ).grid(row=2, column=2, pady=(8, 0), sticky="ew")
        tk.Button(
            network,
            text="填入本机 relay",
            command=self.use_local_relay_server,
            bg="#e7e7e7",
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=5,
        ).grid(row=2, column=3, pady=(8, 0), sticky="ew")
        port_frame = tk.Frame(network, bg="#f6f6f6")
        port_frame.grid(row=2, column=4, pady=(8, 0), sticky="ew")
        ttk.Entry(port_frame, textvariable=self.serial_port_var, width=7).pack(side="left")
        tk.Button(
            port_frame,
            text="写入 ESP32",
            command=lambda: self.run_async(self.configure_esp32_worker),
            bg="#1677ff",
            fg="white",
            activebackground="#0958d9",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=5,
        ).pack(side="left", padx=(6, 0))
        network.grid_columnconfigure(1, weight=2)
        network.grid_columnconfigure(3, weight=1)

        self.log_box = scrolledtext.ScrolledText(
            body,
            height=11,
            wrap="word",
            state="disabled",
            bg="white",
            fg="#333333",
            insertbackground="#333333",
            font=("Microsoft YaHei UI", 9),
            relief="solid",
            borderwidth=1,
        )
        self.log_box.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="稳定语音入口：笔记本麦克风。板载 WakeNet 实验分支不会由本启动器启用。",
            bg="#f6f6f6",
            fg="#777777",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(8, 0))

    def emit(self, kind: str, value: object) -> None:
        self.events.put((kind, value))

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def run_async(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()

    def drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.log(str(value))
                elif kind == "status":
                    self.status_var.set(str(value))
                elif kind == "network":
                    network = value if isinstance(value, dict) else {}
                    self.wifi_ssid_var.set(str(network.get("ssid") or "未连接"))
                    self.lan_ip_var.set(str(network.get("ip") or "未检测到"))
                elif kind == "wifi_password":
                    self.wifi_password_var.set(str(value))
                elif kind == "snapshot":
                    self.apply_snapshot(value if isinstance(value, dict) else {})
                elif kind == "listener_started":
                    self.listener_var.set("正在监听")
                    self.stop_button.configure(state="normal")
                    self.start_button.configure(state="disabled")
                elif kind == "listener_stopped":
                    self.listener_var.set("未启动")
                    self.stop_button.configure(state="disabled")
                    self.start_button.configure(state="normal")
                    self.listener = None
                elif kind == "busy":
                    self.busy = bool(value)
                    if self.listener is None:
                        self.start_button.configure(
                            state="disabled" if self.busy else "normal"
                        )
                elif kind == "error":
                    self.busy = False
                    if self.listener is None:
                        self.start_button.configure(state="normal")
                    messagebox.showerror("启动失败", str(value))
        except queue.Empty:
            pass
        self.root.after(100, self.drain_events)

    def apply_snapshot(self, snapshot: dict) -> None:
        checks = snapshot.get("checks", {})
        self.cloud_var.set("正常" if checks.get("cloud") else "异常")
        self.device_var.set("在线" if checks.get("device") else "离线")
        self.uart_var.set("正常" if checks.get("uart") else "未就绪")
        sensor_count = snapshot.get("sensor_count", 0)
        self.sensor_var.set(f"{sensor_count} 项新鲜" if checks.get("sensors") else "未就绪")

    def toggle_wifi_password(self) -> None:
        self.wifi_password_entry.configure(
            show="" if self.show_wifi_password_var.get() else "*"
        )

    def detect_network_worker(self) -> None:
        self.emit("status", "正在检测物理 Wi-Fi 与本机 IP…")
        try:
            network = detect_current_network()
        except Exception as exc:
            self.emit("status", "网络检测失败")
            self.emit("error", exc)
            return
        self.emit("network", network)
        self.emit(
            "log",
            f"当前物理 Wi-Fi：{network['ssid']}；本机 IPv4：{network['ip']}。已排除 Meta/VPN 地址。",
        )
        self.emit("status", "网络检测完成")

    def read_wifi_password_worker(self) -> None:
        ssid = self.wifi_ssid_var.get().strip()
        if not ssid or ssid in {"待检测", "未连接"}:
            try:
                network = detect_current_network()
            except Exception as exc:
                self.emit("error", exc)
                return
            self.emit("network", network)
            ssid = network["ssid"]
        try:
            password = read_saved_wifi_password(ssid)
        except Exception as exc:
            self.emit("error", exc)
            return
        self.emit("wifi_password", password)
        self.emit("log", f"已读取 Wi-Fi“{ssid}”的 Windows 已保存密钥；密钥不会写入日志或文件。")
        self.emit("status", "Wi-Fi 密钥已填入")

    def use_direct_server(self) -> None:
        self.esp32_server_var.set(DIRECT_ESP32_SERVER)
        self.log("ESP32 服务地址已设为阿里云直连。")

    def use_local_relay_server(self) -> None:
        ip_value = self.lan_ip_var.get().strip()
        if not valid_lan_ipv4(ip_value):
            messagebox.showwarning("尚未检测网络", "请先点击“检测当前网络”。")
            return
        self.esp32_server_var.set(f"http://{ip_value}:8091")
        self.log("ESP32 服务地址已填入本机 relay；仅在你确实启动 relay 时使用。")

    def configure_esp32_worker(self) -> None:
        ssid = self.wifi_ssid_var.get().strip()
        password = self.wifi_password_var.get()
        port_name = self.serial_port_var.get().strip() or "COM8"
        server = self.esp32_server_var.get().strip().rstrip("/")
        if not ssid or ssid in {"待检测", "未连接"}:
            self.emit("error", "请先检测当前网络。")
            return
        if "," in ssid or "\n" in ssid or "\r" in ssid:
            self.emit("error", "当前 ESP32 协议不支持 SSID 中包含逗号或换行。")
            return
        if not password:
            self.emit("error", "请手动输入 Wi-Fi 密钥，或点击读取 Windows 已保存密钥。")
            return
        if any(char in password for char in "\r\n"):
            self.emit("error", "Wi-Fi 密钥不能包含换行。")
            return
        if not re.fullmatch(r"https?://[^/\s]+(?::\d+)?", server):
            self.emit("error", "ESP32 服务地址格式不正确，例如 http://8.163.38.158。")
            return
        self.emit("status", f"正在通过 {port_name} 写入 ESP32…")
        self.emit(
            "log",
            f"正在打开 {port_name}，串口复位后等待 {SERIAL_OPEN_DELAY_SECONDS:.0f} 秒。Wi-Fi 密钥不会显示。",
        )
        try:
            import serial

            responses: list[str] = []
            with serial.Serial(port_name, SERIAL_BAUD, timeout=1) as serial_port:
                time.sleep(SERIAL_OPEN_DELAY_SECONDS)
                for line in (
                    f"CFG:WIFI:{ssid},{password}",
                    f"CFG:SERVER:{server}",
                    "CFG:WIFI:SHOW",
                    "CFG:UART:PING",
                ):
                    serial_port.write((line + "\n").encode("utf-8"))
                    serial_port.flush()
                    time.sleep(0.7)
                    while serial_port.in_waiting:
                        response = serial_port.readline().decode("utf-8", errors="replace").strip()
                        if response:
                            responses.append(response)
        except Exception as exc:
            self.emit("status", "ESP32 配置失败")
            self.emit("error", f"{port_name} 写入失败：{exc}")
            return
        safe_responses = [
            line for line in responses if "password" not in line.casefold()
        ]
        if safe_responses:
            self.emit("log", "ESP32 返回：\n" + "\n".join(safe_responses[-12:]))
        self.emit("log", f"ESP32 已写入 Wi-Fi“{ssid}”和服务地址 {server}。")
        self.emit("status", "ESP32 网络配置完成")

    def check_once(self) -> None:
        self.emit("status", "正在读取云端与硬件状态…")
        try:
            snapshot = readiness_snapshot()
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            self.emit("status", "检查失败")
            self.emit("log", f"状态检查失败：{exc}")
            return
        self.emit("snapshot", snapshot)
        if snapshot["ok"]:
            self.emit("status", "实时检查 PASS")
            self.emit(
                "log",
                "实时检查 PASS：云端、设备、UART、传感器和动作队列均可演示。",
            )
        else:
            failed = "、".join(snapshot["failed"])
            self.emit("status", "硬件尚未就绪")
            self.emit("log", f"当前未通过：{failed}。上电后可点击重新检查。")

    def start_full_demo(self) -> None:
        if self.busy or self.listener is not None:
            return
        self.run_async(self.start_full_demo_worker)

    def start_full_demo_worker(self) -> None:
        self.emit("busy", True)
        deadline = time.monotonic() + READY_WAIT_SECONDS
        self.emit("status", "等待硬件就绪（最多 3 分钟）…")
        while True:
            try:
                snapshot = readiness_snapshot()
                self.emit("snapshot", snapshot)
                if snapshot["ok"]:
                    break
                self.emit(
                    "log",
                    "等待设备："
                    + "、".join(snapshot["failed"])
                    + "。10 秒后自动重试。",
                )
            except Exception as exc:
                self.emit("log", f"状态读取暂时失败：{exc}。10 秒后自动重试。")
            if time.monotonic() >= deadline:
                self.emit("status", "设备未就绪")
                self.emit("busy", False)
                self.emit(
                    "error",
                    "3 分钟内没有等到实时检查通过。请确认 STM32、ESP32S3 已上电并联网，然后重新点击启动。",
                )
                return
            time.sleep(10)

        self.emit("log", "实时检查 PASS，正在打开 Web 控制台。")
        webbrowser.open(f"{BASE_URL}/console")
        try:
            self.launch_listener()
        except Exception as exc:
            self.emit("busy", False)
            self.emit("error", exc)
            return
        self.emit("status", "演示已启动，正在等待关键词")
        self.emit("busy", False)

    def launch_listener(self) -> None:
        listener_path = bundled_path("runtime", "语音监听器.exe")
        if not listener_path.exists():
            raise FileNotFoundError(f"缺少监听程序：{listener_path}")
        stopped = stop_existing_voice_listeners()
        if stopped:
            self.emit(
                "log",
                f"已自动关闭 {len(stopped)} 个旧语音监听进程，避免旧版“灵宝”继续占用麦克风。",
            )
            time.sleep(0.8)
        input_device = self.input_device_var.get().strip() or "1"
        creationflags, startupinfo = hidden_process_flags()
        command = [
            str(listener_path),
            "--base-url",
            BASE_URL,
            "--device-id",
            DEVICE_ID,
            "--input-device",
            input_device,
            "--wake-phrase",
            "你好小鑫",
            "--wake-alias",
            "你好小新",
            "--wake-alias",
            "你好小心",
            "--wake-alias",
            "你好小欣",
            "--stop-phrase",
            "再见小鑫",
            "--no-auto-start-backend",
            "--no-dashboard",
        ]
        self.listener = subprocess.Popen(
            command,
            cwd=package_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        self.emit("listener_started", self.listener.pid)
        self.emit(
            "log",
            f"语音监听已启动（麦克风 {input_device}）。请说“你好小鑫”。",
        )
        threading.Thread(target=self.read_listener_output, daemon=True).start()
        threading.Thread(target=self.wait_listener_exit, daemon=True).start()

    def read_listener_output(self) -> None:
        process = self.listener
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            text = line.strip()
            if text:
                self.emit("log", text)

    def wait_listener_exit(self) -> None:
        process = self.listener
        if process is None:
            return
        return_code = process.wait()
        self.emit("log", f"语音监听已停止（退出码 {return_code}）。")
        self.emit("listener_stopped", return_code)
        self.emit("status", "语音监听已停止")

    def stop_listener(self) -> None:
        process = self.listener
        if process is None or process.poll() is not None:
            return
        self.log("正在停止语音监听…")
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()

    def show_audio_devices(self) -> None:
        self.run_async(self.show_audio_devices_worker)

    def show_audio_devices_worker(self) -> None:
        listener_path = bundled_path("runtime", "语音监听器.exe")
        if not listener_path.exists():
            self.emit("error", f"缺少监听程序：{listener_path}")
            return
        creationflags, startupinfo = hidden_process_flags()
        result = subprocess.run(
            [str(listener_path), "--list-devices"],
            cwd=package_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        output = (result.stdout or result.stderr).strip()
        self.emit("log", "可用麦克风：\n" + output)

    def open_console(self) -> None:
        webbrowser.open(f"{BASE_URL}/console")
        self.log("已打开 Web 控制台。")

    def open_script(self) -> None:
        try:
            open_local_file(bundled_path("答辩演示讲稿.html"))
        except OSError as exc:
            messagebox.showerror("无法打开讲稿", str(exc))

    def open_ppt(self) -> None:
        try:
            open_local_file(bundled_path("智能桌面AI终端_答辩PPT_优化版_2026-06-25.pptx"))
        except OSError as exc:
            messagebox.showerror("无法打开 PPT", str(exc))

    def on_close(self) -> None:
        if self.listener is not None and self.listener.poll() is None:
            if not messagebox.askyesno("退出", "语音监听仍在运行，是否停止监听并退出？"):
                return
            self.stop_listener()
        self.root.destroy()


def self_test(root_path: Path) -> int:
    required = (
        root_path / "runtime" / "语音监听器.exe",
        root_path / "答辩演示讲稿.html",
        root_path / "智能桌面AI终端_答辩PPT_优化版_2026-06-25.pptx",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "root": str(root_path)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--package-root", default="")
    args, _ = parser.parse_known_args()
    if args.self_test:
        root_path = (
            Path(args.package_root).expanduser().resolve()
            if args.package_root
            else package_root()
        )
        return self_test(root_path)

    root = tk.Tk()
    DemoLauncher(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
