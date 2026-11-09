import csv
import json
import os
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import ttk

import sync_local_projects as recovery

state_path = Path.home() / ".codex" / ".codex-global-state.json"


def main():
    window = tk.Tk()
    window.title("项目恢复")
    window.geometry("500x260")
    window.minsize(460, 250)

    content = ttk.Frame(window, padding=24)
    content.pack(fill="both", expand=True)
    ttk.Label(content, text="本机项目恢复", font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w")
    status = tk.StringVar(value="先点击“退出 Codex 进程”，再点击“启动恢复”。")
    ttk.Label(content, textvariable=status, wraplength=420,
              font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=16)
    buttons = ttk.Frame(content)
    buttons.pack(anchor="w")
    pending = None

    def finish(message):
        status.set(message)
        start.configure(state="normal")
        cancel.configure(state="disabled")

    def check():
        nonlocal pending
        pending = None
        try:
            process_list = subprocess.run(
                ["tasklist.exe", "/FO", "CSV", "/NH"], capture_output=True,
                check=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5,
            )
            apps = [row for row in csv.reader(process_list.stdout.decode("mbcs", errors="replace").splitlines())
                    if len(row) > 1 and row[0].lower() in ("chatgpt.exe", "codex.exe")]
            if apps:
                names = "、".join(sorted({row[0] for row in apps}))
                status.set(f"正在等待 {names} 退出（{len(apps)} 个进程）。\n"
                           "请从窗口或系统托盘选择“退出”，此面板会自动继续。")
                pending = window.after(1200, check)
                return
            raw = state_path.read_bytes()
            original = json.loads(raw)
            result, profiles = recovery.patched_state(original)
            if result != original:
                recovery.atomic_apply(state_path, raw, result,
                                      Path(__file__).parent / "project-backups")
            count = len(result["local-projects"])
            finish(f"恢复完成。已核对 {len(profiles)} 个账号配置、{count} 个项目。\n现在可以重新打开 Codex。")
            launch.pack(side="left", padx=(10, 0))
        except Exception as error:
            finish(f"恢复未完成。\n{error}")

    def begin():
        nonlocal pending
        launch.pack_forget()
        start.configure(state="disabled")
        cancel.configure(state="normal")
        status.set("正在检查 Codex 是否已退出…")
        pending = window.after(30, check)

    def stop():
        nonlocal pending
        if pending is not None:
            window.after_cancel(pending)
            pending = None
        finish("已取消等待。可重新点击“启动恢复”。")

    def exit_codex():
        # Limit termination to the installed desktop app, excluding standalone CLI jobs.
        command = (
            "$apps = Get-Process -Name ChatGPT,Codex -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -match "
            "'\\\\WindowsApps\\\\OpenAI\\.Codex_[^\\\\]+\\\\app\\\\(?:ChatGPT|Codex)\\.exe$' }; "
            "$apps | Where-Object { $_.MainWindowHandle -ne 0 } | "
            "ForEach-Object { [void]$_.CloseMainWindow() }; "
            "Start-Sleep -Milliseconds 1500; "
            "$apps | Where-Object { -not $_.HasExited } | "
            "Stop-Process -ErrorAction Stop"
        )
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                           capture_output=True, check=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            if pending is None:
                status.set("已请求退出 Codex。点击“启动恢复”即可检查并恢复。")
        except (subprocess.SubprocessError, OSError) as error:
            status.set(f"退出操作未完成。\n{error}")

    def launch_codex():
        try:
            os.startfile(r"shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App")
        except OSError as error:
            status.set(f"恢复已完成，但无法启动 Codex。\n{error}")

    ttk.Button(buttons, text="退出 Codex 进程", command=exit_codex).pack(side="left")
    start = ttk.Button(buttons, text="启动恢复", command=begin)
    start.pack(side="left", padx=10)
    cancel = ttk.Button(buttons, text="取消等待", command=stop, state="disabled")
    cancel.pack(side="left")
    launch = ttk.Button(buttons, text="启动 Codex", command=launch_codex)
    window.mainloop()


if __name__ == "__main__":
    main()

