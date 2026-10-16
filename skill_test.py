"""skills/ 아래 배포용 스킬 하나를 골라, 탐색기로 고른 폴더나 파일에 적용해 보고 결과물을 검사한다.

흐름
1. skills/<스킬>/SKILL.md 가 있는 스킬 목록에서 하나 고르기
2. 작업 대상(폴더 또는 파일)을 탐색기로 고르기
3. Claude Code CLI(claude -p)가 그 스킬만 담은 임시 플러그인으로 작업 — 결과는 results/<스킬>/<대상>_<시각>/
4. 결과 검사: 만들어진 파일 목록, 기대 결과물(tests/<스킬>.json의 expect) 충족 여부, 대상이 바뀌었는지
   → report.json 저장 후 결과 폴더(와 HTML)를 연다

진행 로그 — logs/<시각>_<스킬>_<대상>.log (단계·Claude 발화·도구 호출 입력과 결과를 시각과 함께)
            logs/<시각>_<스킬>_<대상>.jsonl (claude stream-json 원본 이벤트)

스킬별 테스트 설정(선택) — tests/<스킬>.json
{
  "target": "folder" | "file" | "any",       # 탐색기에서 고를 대상 종류 (기본 any: 실행 때 묻는다)
  "prompt": "... {target} ... {out_dir} ...",  # 지시문. {skill} {target} {out_dir} 치환. 없으면 기본 지시문
  "expect": ["architecture.html", "*.md"],     # 결과 폴더에 있어야 할 파일(glob, 하위 폴더는 **/)
  "allow_target_changes": false,               # 대상 폴더/파일 수정을 허용하는 스킬이면 true
  "open": ["architecture.html"]                # 끝나고 열 파일(glob). 없으면 첫 HTML, 그것도 없으면 폴더
}

실행: python skill_test.py
      python skill_test.py --skill <스킬> --target <폴더|파일> [--no-open]   (창 없이 바로 실행)
"""
import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from tkinter import Tk, Toplevel, Listbox, Label, Button, Frame, StringVar, filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(HERE, "skills")
TESTS_DIR = os.path.join(HERE, "tests")
RESULTS_DIR = os.path.join(HERE, "results")
LOGS_DIR = os.path.join(HERE, "logs")
PLUGIN_NAME = "skill-test"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "bin", "obj", "build", "dist", ".gradle", ".idea"}
TITLE = "스킬 테스트"


class RunLog:
    """진행 로그. 파일 이름(스킬·대상)이 정해지기 전 줄은 모아 두었다가 open() 때 쓴다."""

    def __init__(self, stamp):
        self.stamp = stamp
        self.path = None
        self.raw_path = None
        self._file = None
        self._raw = None
        self._pending = []

    def open(self, name):
        os.makedirs(LOGS_DIR, exist_ok=True)
        base = os.path.join(LOGS_DIR, f"{self.stamp}_{name}" if name else self.stamp)
        self.path, self.raw_path = base + ".log", base + ".jsonl"
        self._file = open(self.path, "w", encoding="utf-8")
        self._file.writelines(self._pending)
        self._file.flush()
        self._pending = []

    def write(self, text, echo=True):
        """echo=True면 터미널에도 찍는다. 로그 파일에는 줄마다 시각을 붙인다."""
        if echo:
            print(text)
        now = time.strftime("%H:%M:%S")
        lines = "".join(f"[{now}] {line}\n" for line in str(text).splitlines() or [""])
        if self._file:
            self._file.write(lines)
            self._file.flush()
        else:
            self._pending.append(lines)

    def raw(self, line):
        if self.raw_path is None:
            return
        if self._raw is None:
            self._raw = open(self.raw_path, "w", encoding="utf-8")
        self._raw.write(line if line.endswith("\n") else line + "\n")
        self._raw.flush()

    def close(self):
        if self._file is None and self._pending:
            self.open("")
        for f in (self._file, self._raw):
            if f:
                f.close()
        self._file = self._raw = None


def clip(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f" …(+{len(text) - limit}자)"


def tool_result_text(content):
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content or "")


def read_frontmatter(skill_md):
    """SKILL.md 머리말에서 name/description만 가볍게 뽑는다."""
    meta = {}
    with open(skill_md, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def list_skills():
    skills = []
    if os.path.isdir(SKILLS_DIR):
        for name in sorted(os.listdir(SKILLS_DIR)):
            md = os.path.join(SKILLS_DIR, name, "SKILL.md")
            if os.path.isfile(md):
                skills.append((name, read_frontmatter(md).get("description", "")))
    return skills


def load_test_config(skill):
    path = os.path.join(TESTS_DIR, f"{skill}.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def choose_skill(root, skills):
    """스킬 목록 창 — 고른 스킬 이름, 취소하면 None."""
    win = Toplevel(root)
    win.title(f"{TITLE} — 스킬 선택")
    win.attributes("-topmost", True)
    win.geometry("640x420")
    chosen = {"name": None}
    desc = StringVar(value="스킬을 고르세요.")

    box = Listbox(win, font=("Malgun Gothic", 11), activestyle="dotbox")
    for name, _ in skills:
        box.insert("end", name)
    box.pack(fill="both", expand=True, padx=12, pady=(12, 6))
    Label(win, textvariable=desc, wraplength=600, justify="left", anchor="w").pack(fill="x", padx=12)

    def on_select(_=None):
        sel = box.curselection()
        if sel:
            desc.set(skills[sel[0]][1] or "(설명 없음)")

    def ok(_=None):
        sel = box.curselection()
        if sel:
            chosen["name"] = skills[sel[0]][0]
            win.destroy()

    buttons = Frame(win)
    buttons.pack(fill="x", padx=12, pady=12)
    Button(buttons, text="취소", width=10, command=win.destroy).pack(side="right")
    Button(buttons, text="선택", width=10, command=ok).pack(side="right", padx=6)
    box.bind("<<ListboxSelect>>", on_select)
    box.bind("<Double-Button-1>", ok)
    box.bind("<Return>", ok)
    box.selection_set(0)
    on_select()
    box.focus_set()
    win.grab_set()
    root.wait_window(win)
    return chosen["name"]


def choose_target(kind, skill):
    """kind: folder | file | any — 고른 경로, 취소하면 None."""
    if kind == "any":
        answer = messagebox.askyesnocancel(TITLE, f"[{skill}] 작업 대상을 고릅니다.\n\n예: 폴더 선택\n아니오: 파일 선택")
        if answer is None:
            return None
        kind = "folder" if answer else "file"
    if kind == "folder":
        path = filedialog.askdirectory(title=f"[{skill}] 작업할 폴더 선택")
    else:
        path = filedialog.askopenfilename(title=f"[{skill}] 작업할 파일 선택")
    return os.path.normpath(path) if path else None


def snapshot(path, exclude=()):
    """대상이 바뀌었는지 보려고 (상대경로 → (크기, 수정시각))을 모은다. 너무 크면 None.
    exclude 폴더(이 프로그램의 results/·logs/ 등)는 대상 안에 있어도 건너뛴다."""
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    if os.path.isfile(path):
        st = os.stat(path)
        return {os.path.basename(path): (st.st_size, st.st_mtime_ns)}
    files = {}
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and os.path.normcase(os.path.join(dirpath, d)) not in skip]
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            files[os.path.relpath(full, path)] = (st.st_size, st.st_mtime_ns)
            if len(files) > 50000:
                return None
    return files


def diff_snapshot(before, after):
    if before is None or after is None:
        return None
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
    }


def list_outputs(out_dir):
    result = []
    for dirpath, _, filenames in os.walk(out_dir):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), out_dir).replace("\\", "/")
            if rel != "report.json":
                result.append(rel)
    return sorted(result)


def match(files, pattern):
    pattern = pattern.replace("\\", "/")
    return [f for f in files if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(os.path.basename(f), pattern)]


def make_plugin(skill):
    """선택한 스킬 하나만 담은 임시 플러그인 — 다른 스킬이 끼어들지 않게 격리한다."""
    tmp = tempfile.mkdtemp(prefix="skill_test_plugin_")
    os.makedirs(os.path.join(tmp, ".claude-plugin"))
    with open(os.path.join(tmp, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name": PLUGIN_NAME, "version": "1.0.0", "description": "Skill_Test 임시 플러그인"}, f)
    shutil.copytree(os.path.join(SKILLS_DIR, skill), os.path.join(tmp, "skills", skill),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return tmp


def build_prompt(skill, target, out_dir, config, allow_changes):
    fields = {"skill": f"{PLUGIN_NAME}:{skill}", "target": target, "out_dir": out_dir}
    if config.get("prompt"):
        body = config["prompt"].format(**fields)
    else:
        kind = "파일" if os.path.isfile(target) else "폴더"
        body = (f"{fields['skill']} 스킬을 사용해서 다음 {kind}에 대해 스킬이 하는 작업을 수행해줘.\n"
                f"- 대상 {kind}: {target}")
    rules = [f"- 반드시 {fields['skill']} 스킬을 Skill 도구로 불러서 그 지시대로 진행할 것",
             f"- 결과물은 모두 {out_dir} 에 저장할 것",
             "- 사용자에게 묻지 말고 합리적인 기본값으로 끝까지 진행할 것 (이 실행은 비대화형 테스트다)",
             "- 브라우저나 뷰어를 직접 열지 말 것 (테스트 프로그램이 연다)"]
    if not allow_changes:
        rules.append("- 대상 폴더/파일 안에는 아무 파일도 만들거나 고치지 말 것")
    rules.append("- 마지막에 만든 결과물 파일 목록과 각 파일의 역할을 짧게 정리할 것")
    return body + "\n" + "\n".join(rules)


def run_claude(claude, prompt, target, out_dir, plugin_dir, log, on_proc=None):
    add_dir = target if os.path.isdir(target) else os.path.dirname(target)
    # 프롬프트는 표준입력으로 넘긴다 — Windows의 claude.cmd(cmd.exe)는 인자 속 줄바꿈에서 명령줄을 끊는다
    cmd = [claude, "-p", "--add-dir", add_dir, "--add-dir", out_dir, "--plugin-dir", plugin_dir,
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Read", "Glob", "Grep", "Write", "Edit", "Skill", "Bash", "TodoWrite",
           "--output-format", "stream-json", "--verbose"]
    summary = {"skill_invoked": False, "result": None, "final_text": ""}
    emit = log.write
    log.write("명령: " + subprocess.list2cmdline(cmd), echo=False)

    proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if on_proc:
        on_proc(proc)
    proc.stdin.write(prompt)
    proc.stdin.close()
    for line in proc.stdout:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            emit(line.rstrip())
            continue
        log.raw(line)
        if event.get("type") == "system" and event.get("subtype") == "init":
            log.write(f"세션 시작: model={event.get('model')} · cwd={event.get('cwd')} · "
                      f"skills={event.get('skills')}", echo=False)
        elif event.get("type") == "user":
            for block in (event.get("message") or {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    mark = "도구 오류" if block.get("is_error") else "도구 결과"
                    log.write(f"    ← {mark}: {clip(tool_result_text(block.get('content')), 800)}", echo=False)
        elif event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    emit(block["text"].strip())
                elif block.get("type") == "tool_use":
                    args = block.get("input", {})
                    if block.get("name") == "Skill":
                        summary["skill_invoked"] = True
                    hint = args.get("command") or args.get("file_path") or args.get("pattern") or args.get("skill") or ""
                    emit(f"  · {block.get('name')} {str(hint)[:160]}")
                    log.write(f"    입력: {clip(json.dumps(args, ensure_ascii=False), 1500)}", echo=False)
        elif event.get("type") == "result":
            summary["result"] = {k: event.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms", "total_cost_usd")}
            summary["final_text"] = event.get("result") or ""
            emit(f"\n[끝] {event.get('subtype')} · {event.get('num_turns')}턴 · "
                 f"{round((event.get('duration_ms') or 0) / 1000)}초 · ${event.get('total_cost_usd') or 0:.2f}")
    proc.wait()
    summary["exit_code"] = proc.returncode
    return summary


def main():
    parser = argparse.ArgumentParser(description="skills/의 스킬을 골라 폴더·파일에 적용해 보고 결과물을 검사한다.")
    parser.add_argument("--skill", help="skills/ 아래 스킬 이름 (주면 선택 창을 건너뛴다)")
    parser.add_argument("--target", help="작업할 폴더나 파일 (주면 탐색기를 건너뛴다)")
    parser.add_argument("--no-open", action="store_true", help="끝나고 결과를 열지 않는다")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    stamp = time.strftime("%Y%m%d_%H%M%S")
    log = RunLog(stamp)
    log.write(f"skill_test 시작 · 인자: {vars(args)}", echo=False)
    try:
        run(args, stamp, log)
    except Exception:
        import traceback
        log.write("[예외]\n" + traceback.format_exc())
        raise
    finally:
        log.write("skill_test 종료", echo=False)
        log.close()


def execute(claude, skill, target, stamp, log, config, on_proc=None):
    """3~4단계 — 스킬을 대상에 적용하고 결과를 검사해 report(dict)를 돌려준다. report.json도 저장한다."""
    target_name = os.path.splitext(os.path.basename(target))[0] or "target"
    log.open(f"{skill}_{target_name}")
    out_dir = os.path.join(RESULTS_DIR, skill, f"{target_name}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    allow_changes = bool(config.get("allow_target_changes"))
    prompt = build_prompt(skill, target, out_dir, config, allow_changes)

    log.write(f"스킬: {skill}")
    log.write(f"대상: {target}")
    log.write(f"결과: {out_dir}")
    log.write(f"로그: {log.path}\n")
    log.write("지시문:\n" + prompt, echo=False)

    # 3. 실행
    # 대상이 이 프로그램 폴더를 품고 있으면, 실행 중 우리가 쓰는 결과·로그는 변경으로 치지 않는다
    own_dirs = (RESULTS_DIR, LOGS_DIR)
    before = snapshot(target, own_dirs)
    log.write(f"대상 스냅샷(실행 전): {'파일 ' + str(len(before)) + '개' if before is not None else '너무 커서 생략'}",
              echo=False)
    plugin_dir = make_plugin(skill)
    log.write(f"임시 플러그인: {plugin_dir}", echo=False)
    started = time.time()
    try:
        summary = run_claude(claude, prompt, target, out_dir, plugin_dir, log, on_proc)
    finally:
        shutil.rmtree(plugin_dir, ignore_errors=True)
    log.write(f"claude 종료 코드: {summary.get('exit_code')}", echo=False)
    after = snapshot(target, own_dirs)

    # 4. 결과 검사
    outputs = list_outputs(out_dir)
    expect = config.get("expect", [])
    expect_results = {p: match(outputs, p) for p in expect}
    target_changes = diff_snapshot(before, after)
    changed = bool(target_changes and any(target_changes.values()))
    checks = {
        "Claude 실행 성공": summary.get("exit_code") == 0 and not (summary.get("result") or {}).get("is_error", True),
        "스킬 호출됨": summary["skill_invoked"],
        "결과물 생성됨": bool(outputs),
        **{f"기대 결과물 {p}": bool(found) for p, found in expect_results.items()},
    }
    if not allow_changes:
        checks["대상 변경 없음"] = not changed if target_changes is not None else None

    report = {
        "skill": skill, "target": target, "out_dir": out_dir, "started": stamp,
        "elapsed_sec": round(time.time() - started), "prompt": prompt,
        "passed": all(v is not False for v in checks.values()),
        "checks": checks, "outputs": outputs, "expect": expect_results,
        "target_changes": target_changes, "claude": summary,
        "log": log.path, "raw_log": log.raw_path,
    }
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log.write("\n=== 검사 결과 ===")
    for name, ok in checks.items():
        log.write(f"  [{'통과' if ok else ('건너뜀' if ok is None else '실패')}] {name}")
    if changed:
        for kind in ("added", "modified", "removed"):
            for path in target_changes[kind][:20]:
                log.write(f"      대상 {kind}: {path}")
    log.write(f"\n결과물 {len(outputs)}개:")
    for path in outputs[:50]:
        log.write(f"  - {path}")
    log.write(f"\n종합: {'통과' if report['passed'] else '실패'}  (report.json: {os.path.join(out_dir, 'report.json')})")
    log.write(f"로그: {log.path}")
    return report


def run(args, stamp, log):
    headless = bool(args.skill and args.target)

    def fail(message):
        log.write(f"[오류] {message}")
        if not headless:
            messagebox.showerror(TITLE, message)

    root = None
    if not headless:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)

    claude = shutil.which("claude")
    if not claude:
        return fail("claude CLI를 찾을 수 없습니다. Claude Code를 설치하세요.")
    skills = list_skills()
    if not skills:
        return fail(f"테스트할 스킬이 없습니다.\n{SKILLS_DIR}\\<스킬>\\SKILL.md 형태로 넣어 주세요.")

    # 1. 스킬 고르기
    if args.skill:
        if args.skill not in [name for name, _ in skills]:
            return fail(f"skills/에 {args.skill} 스킬이 없습니다. 있는 스킬: {', '.join(n for n, _ in skills)}")
        skill = args.skill
    else:
        skill = choose_skill(root, skills)
    if not skill:
        log.write("스킬을 선택하지 않아 종료합니다.")
        return
    config = load_test_config(skill)
    log.write(f"스킬 선택: {skill} · 테스트 설정: {json.dumps(config, ensure_ascii=False) if config else '없음(기본)'}",
              echo=False)

    # 2. 대상 고르기
    if args.target:
        target = os.path.normpath(os.path.abspath(args.target))
        if not os.path.exists(target):
            return fail(f"대상이 없습니다: {target}")
    else:
        target = choose_target(config.get("target", "any"), skill)
    if not target:
        log.write("대상을 선택하지 않아 종료합니다.")
        return
    if root:
        root.destroy()

    report = execute(claude, skill, target, stamp, log, config)

    # 5. 결과 열기
    if args.no_open:
        return
    open_results(report, config, log)


def open_results(report, config, log=None):
    """config.open 에 맞는 파일, 없으면 첫 HTML, 그것도 없으면 결과 폴더를 연다."""
    out_dir, outputs = report["out_dir"], report["outputs"]
    to_open = [m for p in config.get("open", []) for m in match(outputs, p)] or match(outputs, "*.html")[:1]
    if log:
        log.write(f"결과 열기: {to_open or out_dir}", echo=False)
    if to_open:
        for rel in to_open:
            webbrowser.open("file:///" + os.path.join(out_dir, rel).replace("\\", "/"))
    else:
        os.startfile(out_dir)


if __name__ == "__main__":
    main()
