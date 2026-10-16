# EG Skill Tester

Claude Code 스킬을 실제 프로젝트에 적용해 보고 결과물을 검사하는 도구입니다.

`skills/` 폴더에 넣은 스킬 하나를 고르고 작업할 폴더나 파일을 정하면, Claude Code CLI가 **그 스킬만 담은 임시 플러그인**으로 작업합니다. 끝나면 결과물이 제대로 나왔는지, 스킬이 실제로 호출됐는지, 대상 폴더를 건드리지 않았는지 검사합니다.

## 준비

- **Windows** — 결과 열기·프로세스 중지에 Windows 기능(`os.startfile`, `taskkill`)을 씁니다.
- **Python 3** (tkinter 포함, 3.12에서 확인). 추가로 설치할 패키지는 없습니다.
- **Claude Code CLI** — `claude` 명령이 PATH에 있고 로그인되어 있어야 합니다.

  ```bash
  npm install -g @anthropic-ai/claude-code
  claude        # 처음 한 번 로그인
  ```

## 폴더 구성

```
EG_Skill_Tester/
├─ skill_test_gui.py   GUI (권장)
├─ skill_test.py       명령줄 실행 · 실행/검사 로직
├─ assets/icons/       GUI 아이콘 (Lucide)
├─ skills/             테스트할 스킬 — <스킬>/SKILL.md      (git 제외)
├─ tests/              스킬별 테스트 설정 — <스킬>.json (선택)
├─ results/            결과물 — <스킬>/<대상>_<시각>/       (git 제외)
└─ logs/               진행 로그 — <시각>_<스킬>_<대상>.log  (git 제외)
```

`skills/`, `results/`, `logs/`의 내용은 `.gitignore`로 저장소에서 빠집니다. 스킬은 각자 `skills/` 아래에 폴더째 넣어 쓰세요.

```
skills/
└─ my-skill/
   ├─ SKILL.md        ← 이 파일이 있어야 목록에 나옵니다
   ├─ references/
   └─ scripts/
```

## 사용법

### GUI

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

### 명령줄

```bash
python skill_test.py                                   # 선택 창을 차례로 띄움
python skill_test.py --skill <스킬> --target <경로>     # 창 없이 바로 실행
python skill_test.py --skill <스킬> --target <경로> --no-open
```

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

## 라이선스 참고

`assets/icons/`의 아이콘은 [Lucide](https://lucide.dev) (ISC 라이선스) v0.460.0의 SVG와, 이를 18·27·36px PNG로 변환한 파일입니다.
