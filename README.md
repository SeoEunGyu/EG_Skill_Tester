# EG Skill Tester

Claude Code 스킬을 실제 프로젝트에 적용해 보고 결과물을 검사하는 도구입니다.

`skills/` 폴더에 넣은 스킬 하나를 고르고 작업할 폴더나 파일을 정하면, Claude Code CLI가 **그 스킬만 담은 임시 플러그인**으로 작업합니다. 끝나면 결과물이 제대로 나왔는지, 스킬이 실제로 호출됐는지, 대상 폴더를 건드리지 않았는지 검사합니다.

## 요구사항

| 항목 | 내용 | 확인 명령 |
|---|---|---|
| OS | Windows 10 / 11 — 결과 열기·실행 중지에 Windows 기능(`os.startfile`, `taskkill`)을 씁니다. | |
| Python | 3.x, **tkinter 포함** (python.org 설치본에는 기본 포함, 3.12에서 확인) | `python --version`<br>`python -m tkinter` (작은 창이 뜨면 OK) |
| Claude Code CLI | `claude` 명령이 PATH에 있고 로그인되어 있어야 합니다. | `claude --version` |
| Node.js | Claude Code CLI를 npm으로 설치할 때만 필요 | `node --version` |

추가로 설치할 Python 패키지는 없습니다 (표준 라이브러리만 사용).

## 실행 방법

### 1. 설치

```bash
git clone <저장소 주소>
cd EG_Skill_Tester

# Claude Code CLI가 없다면 설치 후 한 번 로그인
npm install -g @anthropic-ai/claude-code
claude
```

### 2. 테스트할 스킬 넣기

`skills/` 아래에 스킬 폴더를 통째로 복사합니다. 폴더 안에 `SKILL.md`가 있어야 목록에 나옵니다.

```
skills/
└─ my-skill/
   ├─ SKILL.md
   ├─ references/
   └─ scripts/
```

필요하면 `tests/my-skill.json`으로 스킬별 테스트 설정을 둡니다 ([아래](#스킬별-테스트-설정-선택) 참고).

### 3. 실행 — GUI (권장)

```bash
python skill_test_gui.py
# 콘솔 창 없이: pythonw skill_test_gui.py
```

1. **스킬 선택** — `skills/` 아래 스킬 폴더 목록에서 하나를 고릅니다. 새로 넣은 스킬은 새로고침 버튼으로 다시 읽습니다.
2. **작업 대상** — 폴더 / 파일 아이콘 버튼으로 고르거나 경로를 직접 입력합니다.
3. **실행** — 진행 로그에 Claude의 발화와 도구 호출이 실시간으로 나옵니다. 상태줄에 경과 시간이 표시되고, **중지**로 언제든 멈출 수 있습니다.
4. **검사 결과** — 항목별 통과 / 실패, 결과물 목록, 대상 변경 내역이 나옵니다. 결과물 파일은 더블클릭하면 열립니다.
   - 제목 줄 오른쪽 버튼: 검사 결과(HTML 등) 열기, 결과 폴더 열기, 로그 파일 열기
   - **끝나면 결과 열기**를 켜 두면 완료 후 자동으로 엽니다.

### 4. 실행 — 명령줄

```bash
python skill_test.py                                   # 선택 창을 차례로 띄움
python skill_test.py --skill <스킬> --target <경로>     # 창 없이 바로 실행
python skill_test.py --skill <스킬> --target <경로> --no-open
```

결과는 `results/<스킬>/<대상>_<시각>/`, 로그는 `logs/`에 남습니다.

## 폴더 구성

```
EG_Skill_Tester/
├─ skill_test_gui.py   GUI (권장)
├─ skill_test.py       명령줄 실행 · 실행/검사 로직
├─ assets/icons/       GUI 아이콘 (Lucide)
├─ LICENSE             PolyForm Noncommercial 1.0.0
├─ skills/             테스트할 스킬 — <스킬>/SKILL.md      (git 제외)
├─ tests/              스킬별 테스트 설정 — <스킬>.json (선택)
├─ results/            결과물 — <스킬>/<대상>_<시각>/       (git 제외)
└─ logs/               진행 로그 — <시각>_<스킬>_<대상>.log  (git 제외)
```

`skills/`, `results/`, `logs/`의 내용은 `.gitignore`로 저장소에서 빠집니다. 스킬은 각자 `skills/` 아래에 넣어 쓰세요.

## 동작 방식

1. 고른 스킬 폴더만 복사한 임시 플러그인(`skill-test`)을 만듭니다. 다른 스킬이 끼어들지 않게 격리하기 위해서입니다.
2. `claude -p`를 비대화형으로 실행합니다. 지시문에는 다음 규칙이 붙습니다.
   - `skill-test:<스킬>` 스킬을 Skill 도구로 불러 그 지시대로 진행할 것
   - 결과물은 모두 결과 폴더에 저장할 것
   - 사용자에게 묻지 말고 기본값으로 끝까지 진행할 것
   - 대상 폴더/파일은 수정하지 말 것 (`allow_target_changes`가 아니면)
3. 허용 도구는 `Read Glob Grep Write Edit Skill Bash TodoWrite`, 권한 모드는 `acceptEdits`입니다. 접근 가능한 폴더는 대상 폴더와 결과 폴더입니다.
4. 실행 전후로 대상 폴더의 파일 목록(크기·수정 시각)을 비교해 변경 여부를 확인합니다.

> 실제 Claude 호출이므로 실행할 때마다 사용량(비용)이 듭니다. 상태줄과 로그에 실행 비용이 표시됩니다.

## 스킬별 테스트 설정 (선택)

`tests/<스킬>.json`을 두면 그 스킬을 실행할 때 적용됩니다. 없으면 기본값으로 실행합니다.

```json
{
  "target": "folder",
  "prompt": "{skill} 스킬로 {target} 프로젝트의 아키텍처를 분석해서 {out_dir}에 저장해줘",
  "expect": ["architecture.html", "*.md"],
  "allow_target_changes": false,
  "open": ["architecture.html"]
}
```

| 키 | 설명 | 기본값 |
|---|---|---|
| `target` | 대상 종류 — `folder` / `file` / `any`. GUI에서 맞지 않는 선택 버튼이 꺼집니다. | `any` |
| `prompt` | 지시문. `{skill}` `{target}` `{out_dir}`가 치환됩니다. | 스킬을 대상에 적용하라는 기본 지시문 |
| `expect` | 결과 폴더에 있어야 할 파일 (glob, 하위 폴더는 `**/`) | 없음 |
| `allow_target_changes` | 대상 폴더/파일 수정을 허용하는 스킬이면 `true` | `false` |
| `open` | 끝나고 열 파일 (glob) | 첫 HTML, 없으면 결과 폴더 |

## 검사 항목

| 항목 | 통과 조건 |
|---|---|
| Claude 실행 성공 | 종료 코드 0, 결과가 오류가 아님 |
| 스킬 호출됨 | Claude가 Skill 도구를 호출함 |
| 결과물 생성됨 | 결과 폴더에 파일이 하나 이상 있음 |
| 기대 결과물 `<패턴>` | `expect`의 패턴마다 맞는 파일이 있음 |
| 대상 변경 없음 | 대상 폴더/파일이 실행 전과 같음 (`allow_target_changes`면 생략) |

모든 항목이 통과(또는 건너뜀)이면 종합 **통과**입니다.

## 결과물

- `results/<스킬>/<대상>_<시각>/` — 스킬이 만든 파일들과 `report.json`
  - `report.json`: 검사 항목, 결과물 목록, 대상 변경 내역, 지시문, 소요 시간, 비용, 로그 경로
- `logs/<시각>_<스킬>_<대상>.log` — 단계 · Claude 발화 · 도구 호출 입력과 결과 (시각 포함)
- `logs/<시각>_<스킬>_<대상>.jsonl` — `claude --output-format stream-json` 원본 이벤트

## 라이선스

이 프로젝트는 [PolyForm Noncommercial License 1.0.0](LICENSE)을 따릅니다. **비상업적 용도**(개인 학습·연구, 비영리 단체 등)로는 자유롭게 사용·수정·배포할 수 있으며, **상업적 사용은 허용되지 않습니다.**

Copyright (c) 2026 SeoEunGyu

GUI 아이콘은 [Lucide](https://lucide.dev)를 사용했습니다.
