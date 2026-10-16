"""스킬 테스트 GUI — skill_test.py 의 흐름(스킬 선택 → 대상 선택 → 실행 → 결과 검사)을 창 하나에서 한다.

실행: python skill_test_gui.py   (콘솔 없이: pythonw skill_test_gui.py)
"""
import os
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

import skill_test as st

ICONS_DIR = os.path.join(st.HERE, "assets", "icons")  # Lucide 아이콘(ISC) — SVG 원본과 18/27/36px PNG
FONT = ("Malgun Gothic", 10)
MONO = ("Consolas", 10)


class GuiLog(st.RunLog):
    """로그 파일에 쓰면서, 화면에 보일 줄(echo=True)은 큐로 넘긴다 — 작업 스레드에서 Tk를 직접 만지지 않게."""

    def __init__(self, stamp, lines):
        super().__init__(stamp)
        self.lines = lines

    def write(self, text, echo=True):
        super().write(text, echo=False)
        if echo:
            self.lines.put(("log", str(text)))


class Tooltip:
    """아이콘 버튼에 마우스를 올리면 잠깐 뜨는 설명."""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, _=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, font=FONT, background="#ffffe1", relief="solid", borderwidth=1,
                 padx=6, pady=2).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, root):
        self.root = root
        self.claude = shutil.which("claude")
        self.skills = []
        self.events = queue.Queue()
        self.proc = None
        self.worker = None
        self.started = None
        self.report = None
        self.config = {}
        self.stopped = False

        root.title(st.TITLE)
        # 화면 배율(125%·200% 등)만큼 키우고, 모니터보다 크지 않게 맞춘다
        scale = self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = min(int(560 * scale), sw - int(40 * scale))
        h = min(int(460 * scale), sh - int(90 * scale))
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        root.minsize(int(460 * scale), int(420 * scale))
        style = ttk.Style()
        style.configure(".", font=FONT)
        # 검사 결과 줄 높이 — 고정 px이면 고배율 화면에서 글자가 겹치므로 글꼴 높이로 정한다
        line = tkfont.Font(root=root, font=FONT).metrics("linespace")
        style.configure("Treeview", rowheight=line + int(6 * scale))
        # 실행·중지 버튼은 기본 버튼 높이의 1.5배 — 위아래 여백을 늘린다
        base = ttk.Button(root, text="가").winfo_reqheight()
        extra = max(1, round(base * 0.25))
        style.configure("Run.TButton", font=(FONT[0], 10, "bold"), padding=(int(6 * scale), extra))
        style.configure("Stop.TButton", padding=(int(6 * scale), extra))
        style.configure("Section.TLabelframe.Label", font=FONT)
        style.configure("Icon.TButton", padding=int(2 * scale))

        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(10, 0, 10, 4)).pack(side="bottom", fill="x")
        self._build(root)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.reload_skills()
        self.set_running(False)
        if not self.claude:
            self.status.set("claude CLI를 찾을 수 없습니다. Claude Code를 설치하세요.")
        self.root.after(100, self.pump)

    # ---------- 화면 구성 (세로 1열: 스킬 → 대상 → 실행 버튼 → 로그 → 검사 결과) ----------
    def _build(self, root):
        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        # 스킬 선택
        sec = ttk.Frame(frame)
        sec.pack(fill="x")
        head = ttk.Frame(sec)
        head.pack(fill="x")
        title = ttk.Label(head, text="스킬 선택")
        title.pack(side="left")
        self.icon_button(head, "refresh-cw", "새로고침", self.reload_skills).pack(side="right")
        self.icon_button(head, "folder-open", "skills 폴더 열기",
                         lambda: os.startfile(st.SKILLS_DIR)).pack(side="right", padx=(0, 4))
        self.dotted_line(head, title)
        self.skill_box = tk.Listbox(sec, font=(FONT[0], 11), activestyle="none", exportselection=False, height=3)
        self.skill_box.pack(fill="x", pady=(int(6 * self.scale), 0))
        self.skill_box.bind("<<ListboxSelect>>", lambda _: self.on_skill_select())

        # 작업 대상
        tgt = ttk.LabelFrame(frame, text="작업 대상", style="Section.TLabelframe", padding=8)
        tgt.pack(fill="x", pady=(10, 0))
        self.target = tk.StringVar()
        ttk.Entry(tgt, textvariable=self.target, font=FONT).pack(side="left", fill="x", expand=True)
        self.btn_folder = self.icon_button(tgt, "folder", "폴더 선택", lambda: self.pick_target("folder"), "folder-gray")
        self.btn_folder.pack(side="left", padx=(6, 0))
        self.btn_file = self.icon_button(tgt, "file", "파일 선택", lambda: self.pick_target("file"), "file-gray")
        self.btn_file.pack(side="left", padx=(4, 0))

        # 실행 · 중지 · 결과 열기
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=10)
        play, play_off = self.icon("play-blue"), self.icon("play-gray")
        stop, stop_off = self.icon("square-red"), self.icon("square-gray")
        self.btn_run = ttk.Button(bar, text="실행", image=(play, "disabled", play_off), compound="left",
                                  style="Run.TButton", command=self.start)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="중지", image=(stop, "disabled", stop_off), compound="left",
                                   style="Stop.TButton", command=self.stop)
        self.btn_stop.pack(side="left", padx=4)
        self.auto_open = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="끝나면 결과 열기", variable=self.auto_open).pack(side="left", padx=(2, 0))

        # 로그·검사 결과 사이 경계는 끌어서 조절 — 각 영역은 최소 높이 아래로 줄지 않는다
        vpaned = tk.PanedWindow(frame, orient="vertical", sashwidth=int(6 * self.scale), sashrelief="flat",
                                background=ttk.Style().lookup("TFrame", "background"))
        vpaned.pack(fill="both", expand=True)

        # 진행 로그 — 제목 줄 오른쪽에 로그 파일 열기 아이콘 버튼
        log_frame = ttk.Frame(vpaned)
        log_head = ttk.Frame(log_frame)
        log_head.pack(fill="x", pady=(0, int(6 * self.scale)))
        log_title = ttk.Label(log_head, text="진행 로그")
        log_title.pack(side="left")
        self.btn_log = self.icon_button(log_head, "file-text", "로그 파일 열기",
                                        lambda: self.open_path("log"), "file-text-gray")
        self.btn_log.pack(side="right")
        self.dotted_line(log_head, log_title)
        self.log = ScrolledText(log_frame, wrap="word", font=MONO, state="disabled", height=3,
                                background="#ffffff", foreground="#1f2328", insertbackground="#1f2328")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("tool", foreground="#0550ae")
        self.log.tag_configure("pass", foreground="#1a7f37")
        self.log.tag_configure("fail", foreground="#cf222e")
        self.log.tag_configure("head", foreground="#6f42c1")
        vpaned.add(log_frame, minsize=int(110 * self.scale), stretch="always")

        # 검사 결과 — 제목 줄 오른쪽에 결과 열기·결과 폴더 열기 아이콘 버튼
        check_frame = ttk.Frame(vpaned, padding=(0, 4, 0, 0))
        check_head = ttk.Frame(check_frame)
        check_head.pack(fill="x", pady=(0, int(6 * self.scale)))
        check_title = ttk.Label(check_head, text="검사 결과")
        check_title.pack(side="left")
        self.btn_dir = self.icon_button(check_head, "folder-open", "결과 폴더 열기",
                                        lambda: self.open_path("out_dir"), "folder-open-gray")
        self.btn_dir.pack(side="right")
        self.btn_open = self.icon_button(check_head, "external-link", "검사 결과 열기", self.open_result,
                                         "external-link-gray")
        self.btn_open.pack(side="right", padx=(0, 4))
        self.dotted_line(check_head, check_title)
        self.checks = ttk.Treeview(check_frame, columns=("result",), height=3)
        self.checks.heading("#0", text="항목", anchor="w")
        self.checks.heading("result", text="결과", anchor="w")
        self.checks.column("#0", width=300)
        self.checks.column("result", width=100, stretch=False)
        self.checks.tag_configure("pass", foreground="#1a7f37")
        self.checks.tag_configure("fail", foreground="#cf222e")
        self.checks.tag_configure("skip", foreground="#888888")
        self.checks.pack(fill="both", expand=True)
        self.checks.bind("<Double-1>", self.on_check_double)
        vpaned.add(check_frame, minsize=int(110 * self.scale), stretch="never")

    def icon(self, name, size=18):
        """Lucide 아이콘 PNG — 화면 배율에 가장 가까운 크기(18/27/36px)를 고른다."""
        px = min((18, 27, 36), key=lambda p: abs(p - size * self.scale))
        image = tk.PhotoImage(file=os.path.join(ICONS_DIR, f"{name}_{px}.png"))
        self.icons = getattr(self, "icons", []) + [image]  # 참조를 잡아 두지 않으면 이미지가 사라진다
        return image

    def dotted_line(self, parent, label):
        """제목(label)과 오른쪽 버튼 사이를 잇는 가로 점선 — 제목 글자 높이의 가운데에 긋는다.
        제목·버튼을 pack 한 뒤에 부른다(남은 폭을 채운다)."""
        gap = int(8 * self.scale)
        canvas = tk.Canvas(parent, height=1, highlightthickness=0,
                           background=ttk.Style().lookup("TFrame", "background"))
        canvas.pack(side="left", fill="both", expand=True, padx=(gap, gap))
        dash = (max(1, round(2 * self.scale)), max(2, round(3 * self.scale)))

        def redraw(_=None):
            canvas.delete("all")
            y = label.winfo_rooty() + label.winfo_height() // 2 - canvas.winfo_rooty()
            canvas.create_line(0, y, canvas.winfo_width(), y, fill="#b8bcc2", dash=dash,
                               width=max(1, round(self.scale)))

        canvas.bind("<Configure>", redraw)
        label.bind("<Configure>", redraw, add="+")

    def icon_button(self, parent, name, tip, command, disabled=None):
        """아이콘만 있는 버튼. disabled 아이콘을 주면 꺼졌을 때 그것으로 바꾼다. 마우스를 올리면 설명을 띄운다."""
        image = self.icon(name)
        if disabled:
            image = (image, "disabled", self.icon(disabled))
        button = ttk.Button(parent, image=image, command=command, style="Icon.TButton")
        Tooltip(button, tip)
        return button

    # ---------- 스킬 / 대상 ----------
    def reload_skills(self):
        current = self.selected_skill()
        self.skills = st.list_skills()
        self.skill_box.delete(0, "end")
        for name, _ in self.skills:
            self.skill_box.insert("end", name)
        names = [n for n, _ in self.skills]
        if names:
            idx = names.index(current) if current in names else 0
            self.skill_box.selection_set(idx)
            self.skill_box.see(idx)
        self.on_skill_select()
        if not self.skills:
            self.status.set(f"테스트할 스킬이 없습니다. {st.SKILLS_DIR}\\<스킬>\\SKILL.md 형태로 넣어 주세요.")

    def selected_skill(self):
        sel = self.skill_box.curselection() if hasattr(self, "skill_box") else ()
        return self.skills[sel[0]][0] if sel else None

    def on_skill_select(self):
        skill = self.selected_skill()
        try:
            config = st.load_test_config(skill) if skill else {}
        except (OSError, ValueError) as e:
            config = {}
            self.status.set(f"tests/{skill}.json 읽기 실패 — 기본 설정으로 실행합니다: {e}")
        self.config = config
        kind = config.get("target", "any")
        self.btn_folder.configure(state="disabled" if kind == "file" else "normal")
        self.btn_file.configure(state="disabled" if kind == "folder" else "normal")

    def pick_target(self, kind):
        skill = self.selected_skill() or ""
        start = self.target.get().strip()
        start = start if os.path.isdir(start) else os.path.dirname(start) if start else None
        if kind == "folder":
            path = filedialog.askdirectory(title=f"[{skill}] 작업할 폴더 선택", initialdir=start)
        else:
            path = filedialog.askopenfilename(title=f"[{skill}] 작업할 파일 선택", initialdir=start)
        if path:
            self.target.set(os.path.normpath(path))

    # ---------- 실행 ----------
    def set_running(self, running):
        idle = "disabled" if running else "normal"
        self.btn_run.configure(state=idle)
        self.btn_stop.configure(state="normal" if running else "disabled")
        self.skill_box.configure(state=idle)
        has_report = "normal" if (self.report and not running) else "disabled"
        for b in (self.btn_open, self.btn_dir, self.btn_log):
            b.configure(state=has_report)

    def start(self):
        skill = self.selected_skill()
        target = self.target.get().strip().strip('"')
        if not self.claude:
            return messagebox.showerror(st.TITLE, "claude CLI를 찾을 수 없습니다. Claude Code를 설치하세요.")
        if not skill:
            return messagebox.showwarning(st.TITLE, "스킬을 고르세요.")
        if not target:
            return messagebox.showwarning(st.TITLE, "작업 대상(폴더 또는 파일)을 고르세요.")
        target = os.path.normpath(os.path.abspath(target))
        if not os.path.exists(target):
            return messagebox.showerror(st.TITLE, f"대상이 없습니다:\n{target}")
        kind = self.config.get("target", "any")
        if (kind == "folder" and not os.path.isdir(target)) or (kind == "file" and not os.path.isfile(target)):
            return messagebox.showwarning(st.TITLE, f"이 스킬은 대상으로 {'폴더' if kind == 'folder' else '파일'}를 받습니다.")

        self.report = None
        self.stopped = False
        self.checks.delete(*self.checks.get_children())
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.started = time.time()
        self.set_running(True)
        config = dict(self.config)
        self.worker = threading.Thread(target=self.work, args=(skill, target, config), daemon=True)
        self.worker.start()
        self.tick()

    def work(self, skill, target, config):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        log = GuiLog(stamp, self.events)
        log.write(f"skill_test_gui 시작 · 스킬={skill} · 대상={target}", echo=False)
        try:
            report = st.execute(self.claude, skill, target, stamp, log, config,
                                on_proc=lambda p: setattr(self, "proc", p))
            self.events.put(("done", (report, config)))
        except Exception:
            import traceback
            log.write("[예외]\n" + traceback.format_exc())
            self.events.put(("done", (None, config)))
        finally:
            self.proc = None
            log.write("skill_test_gui 종료", echo=False)
            log.close()

    def stop(self):
        proc = self.proc
        if not proc or proc.poll() is not None:
            return
        if not messagebox.askyesno(st.TITLE, "실행 중인 Claude를 중지할까요?"):
            return
        self.stopped = True
        # claude.cmd → cmd.exe → node 로 이어지므로 프로세스 트리째 끈다
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.append("\n[중지 요청됨]", "fail")

    def tick(self):
        if self.worker and self.worker.is_alive():
            sec = int(time.time() - self.started)
            self.status.set(f"실행 중 · {sec // 60}:{sec % 60:02d}")
            self.root.after(1000, self.tick)

    def pump(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.append(payload)
                elif kind == "done":
                    self.finish(*payload)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def append(self, text, tag=None):
        if tag is None:
            s = text.lstrip()
            tag = ("tool" if s.startswith("· ") else "pass" if s.startswith(("[통과]", "종합: 통과"))
                   else "fail" if s.startswith(("[실패]", "종합: 실패", "[오류]", "[예외]"))
                   else "head" if s.startswith(("===", "[끝]", "스킬:", "대상:", "결과:", "로그:")) else None)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def finish(self, report, config):
        self.report = report
        self.set_running(False)
        if report is None:
            self.status.set("오류로 중단되었습니다. 로그를 확인하세요.")
            return
        for name, ok in report["checks"].items():
            tag, text = ("pass", "통과") if ok else ("skip", "건너뜀") if ok is None else ("fail", "실패")
            self.checks.insert("", "end", text=name, values=(text,), tags=(tag,))
        outputs = self.checks.insert("", "end", text=f"결과물 {len(report['outputs'])}개", values=("",), open=False)
        for rel in report["outputs"]:
            self.checks.insert(outputs, "end", text=rel, values=("",), tags=("file",))
        changes = report.get("target_changes") or {}
        if any(changes.values()):
            node = self.checks.insert("", "end", text="대상 변경 내역", values=("",))
            for k in ("added", "modified", "removed"):
                for p in changes[k]:
                    self.checks.insert(node, "end", text=f"{k}: {p}", values=("",))

        verdict = "중지됨" if self.stopped else ("통과" if report["passed"] else "실패")
        claude = report["claude"].get("result") or {}
        self.status.set(f"종합: {verdict} · {report['elapsed_sec']}초 · "
                        f"${claude.get('total_cost_usd') or 0:.2f} · {report['out_dir']}")
        if self.auto_open.get() and not self.stopped and report["outputs"]:
            self.open_result()

    # ---------- 결과 열기 ----------
    def open_result(self):
        if self.report:
            st.open_results(self.report, self.config)

    def open_path(self, key):
        path = self.report and self.report.get(key)
        if path and os.path.exists(path):
            os.startfile(path)

    def on_check_double(self, _):
        item = self.checks.focus()
        if self.report and "file" in self.checks.item(item, "tags"):
            path = os.path.join(self.report["out_dir"], self.checks.item(item, "text"))
            if os.path.exists(path):
                os.startfile(path)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(st.TITLE, "실행 중입니다. 중지하고 닫을까요?"):
                return
            if self.proc and self.proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
