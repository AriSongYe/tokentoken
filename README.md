# TokenToken

Claude Code와 Codex의 토큰 사용량, 구독 한도(5시간/주간 %)를 한 화면에서 보여주는 Windows용 위젯입니다. 항상 위에 떠 있고 크기를 자유롭게 바꿀 수 있습니다. 같은 데이터를 MCP 서버로도 제공해서, Claude나 Codex에 "내 토큰 사용량 알려줘"라고 물어볼 수 있습니다.

<p>
  <img src="docs/preview.png" width="260" alt="TokenToken 위젯">
  &nbsp;
  <img src="docs/preview-compact.png" width="300" alt="간단 모드">
</p>

<sub>스크린샷은 테스트 데이터로 찍었습니다.</sub>

## 주요 기능
- **항상 위 고정 위젯**: 테두리 없는 창, 드래그로 이동, ◢ 모서리로 크기 조절. 글자와 막대가 창 크기에 맞춰 커지거나 작아집니다.
- **간단 모드**: 창을 낮게 줄이면 한도 막대만 남습니다.
- **Claude 계정 여러 개 지원**: `~/.claude`, `~/.claude-work`, `~/.claude-personal`처럼 `CLAUDE_CONFIG_DIR`로 나눈 계정을 각각 따로 보여줍니다.
- **Codex 지원**: Codex CLI와 VS Code 확장이 남긴 세션 기록을 읽습니다.
- **MCP 서버**: Claude Code, Codex, Claude Desktop에 자동으로 등록합니다.
- **설치 프로그램**: Python 설치 없이 동작합니다. 관리자 권한이 필요 없고, Windows 시작 시 자동 실행됩니다.
- 표준 라이브러리만 사용하며 외부 패키지가 필요 없습니다.

## 표시 항목
| 항목 | 데이터 출처 |
|---|---|
| Claude 5시간/주간 한도 % | 각 계정 폴더의 `.credentials.json` 로그인 정보로 Claude Code `/usage`와 같은 엔드포인트 조회 |
| Claude 오늘 / 현재 5시간 블록 / 최근 7일 토큰 | `<계정 폴더>/projects/**/*.jsonl` |
| Codex 5시간/주간 한도 % | `~/.codex/sessions/**/*.jsonl`의 최신 `rate_limits` |
| Codex 오늘 / 최근 7일 토큰 | 같은 Codex 세션 기록 |

이 PC에 남은 기록을 읽기 때문에 웹이나 모바일 앱에서 쓴 토큰 수는 포함되지 않습니다. 한도 %는 계정 전체 기준입니다.

## 설치

### 방법 1. 설치 프로그램 (권장)
1. `TokenToken-Setup-x.y.z.exe`를 실행합니다. 설치 파일을 만드는 방법은 아래 [설치 프로그램 빌드](#설치-프로그램-빌드)를 참고하세요.
2. 설치할 항목을 고릅니다. 모두 기본으로 켜져 있습니다.
   - Windows 시작 시 자동 실행
   - 바탕화면 바로가기
   - MCP 서버 등록
3. 설치 위치는 `%LOCALAPPDATA%\Programs\TokenToken`입니다.

제거는 Windows 설정 → 앱 → TokenToken에서 합니다. 제거하면 MCP 등록과 자동 실행도 함께 해제됩니다.

> 서명되지 않은 설치 파일이라 SmartScreen 경고가 뜰 수 있습니다. "추가 정보" → "실행"을 누르세요.

### 방법 2. 소스로 실행
Python 3.9 이상이 필요합니다. python.org 설치본에는 tkinter가 포함되어 있습니다.

```bat
git clone https://github.com/AriSongYe/tokentoken.git
cd tokentoken
run.bat             :: 위젯 실행
install_mcp.bat     :: MCP 서버 등록 (해제: install_mcp.bat --remove)
```

## 사용법
- 드래그하면 창이 이동하고, 오른쪽 아래 ◢를 드래그하면 크기가 바뀝니다.
- `● 고정`을 누르면 항상 위에 고정을 켜고 끕니다. `⟳`는 새로고침, `✕`는 종료입니다.
- 우클릭 메뉴에서 바꿀 수 있는 것: 테두리 없는 모드, 투명도, 테마(다크/라이트), Claude/Codex 표시 여부, 새로고침 주기, MCP 등록, Windows 시작 시 실행
- 이미 실행 중이면 두 번째 창은 뜨지 않습니다.

## MCP 연동
등록되는 곳:

| 클라이언트 | 방식 |
|---|---|
| Claude Code | `claude mcp add --scope user tokentoken ...` (CLI가 없으면 `~/.claude.json`에 직접 기록) |
| Codex | `codex mcp add tokentoken ...` (CLI가 없으면 `~/.codex/config.toml`에 직접 기록) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (앱을 재시작해야 적용) |

제공하는 도구:

```text
get_token_usage(provider = "all" | "claude" | "codex", format = "text" | "json")
```

수정되는 설정 파일은 `*.bak_tokentoken` 이름으로 백업됩니다.

## 설정
설정 파일 위치는 `%APPDATA%\TokenToken\config.json`이며, 우클릭 → "설정 파일 위치 열기"로 열 수 있습니다.

| 키 | 기본값 | 설명 |
|---|---|---|
| `refresh_sec` | 30 | 새로고침 주기(초) |
| `claude_api` | true | Claude 구독 한도 % 조회 여부 |
| `claude_api_interval` | 90 | 한도 조회 최소 간격(초) |
| `claude_dirs` | [] | 자동으로 찾지 못하는 Claude 설정 폴더 추가 |
| `show_idle_claude` | false | 최근 사용 기록도 유효한 로그인도 없는 계정 폴더까지 표시 |
| `claude_block_limit` | 0 | 0보다 크면, 한도 API가 없을 때 5시간 블록 토큰 / 이 값으로 % 추정 |
| `alpha`, `theme`, `topmost`, `frameless`, `geometry` | | 창 설정 (메뉴에서 바뀜) |

## 참고 사항
- Claude 한도 엔드포인트(`/api/oauth/usage`)는 공식 문서에 없는 API라 바뀔 수 있습니다. 실패하면 토큰 수만 표시됩니다.
- 로그인 토큰이 만료되면 마지막으로 받은 한도 값을 "N분 전 기준"으로 보여줍니다. 그 계정으로 Claude Code를 쓰면 토큰이 갱신되고 실시간 값으로 돌아옵니다.
- 이 프로그램은 로그인 토큰을 갱신하거나 외부로 보내지 않습니다. 네트워크 요청은 Anthropic 한도 조회 한 가지뿐입니다.
- Codex 한도 %는 Codex를 마지막으로 쓴 시점의 값입니다. 리셋 시각이 지나면 0%로 표시됩니다.

## 프로젝트 구조
```text
tokenmon.pyw          위젯 (tkinter)
usage_core.py         로그 파싱, 한도 조회, 요약
tokentoken_mcp.py     MCP 서버 (stdio JSON-RPC)
install_mcp.py        Claude Code / Codex / Claude Desktop 등록
run.bat, install_mcp.bat
installer/            설치 프로그램 빌드 (NSIS + 런처)
docs/                 스크린샷
```

## 설치 프로그램 빌드
Linux(Ubuntu)에서 빌드합니다.

```bash
sudo apt-get install nsis mingw-w64 curl
bash installer/build_installer.sh   # 저장소 루트에 TokenToken-Setup-x.y.z.exe 생성
```

- [python-build-standalone](https://github.com/astral-sh/python-build-standalone)의 Windows용 Python 3.12(tkinter 포함)를 받아 `runtime/`으로 함께 넣습니다.
- `TokenToken.exe`는 `runtime\pythonw.exe -I app\tokenmon.pyw`를 실행하는 작은 런처입니다.
- 자동 실행은 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`에 등록됩니다.
