# Re AI

> 산업폐기물과 부산물의 재활용 경로를 찾는 AI 서비스  
> AI 부트캠프 경진대회 · Microsoft 주제 · 4인 팀 프로젝트 · 개발 중

## 왜 이 주제를 골랐나

산업현장에서 나온 부산물을 다른 기업이 원료로 쓰려면, 공급하는 부산물의 품질과 오염 상태가 수요 기업이 요구하는 규격에 맞는지 확인해야 합니다. 저희 팀은 “이 부산물을 어디에 쓸 수 있을까?”와 “조건이 맞지 않는다면 무엇을 더 확인해야 할까?”라는 질문에서 시작했습니다.

Re AI는 사용자가 부산물 정보를 입력하면 재활용 경로를 검토하고, 해당 부산물을 활용할 수 있는 업종과 업체를 찾도록 돕는 서비스입니다.

## 내가 맡은 일

저는 **AI 채팅 화면과 문서함의 UI/UX**를 맡았습니다. 채팅에서는 앞서 나눈 내용을 보며 후속 질문을 이어갈 수 있게 했습니다. 요청서를 작성하는 흐름은 문서함과 연결해, 사용자가 나중에 다시 들어와도 작성한 문서를 찾을 수 있도록 설계했습니다.

팀원들이 개발한 에이전트를 한 웹서비스로 연결하기 위해 **Azure에서 서버를 실행할 환경**도 준비하고 있습니다.

## 지금까지 확인한 것

- 회원가입 과정에서 인증 메일이 발송되고 이메일 인증이 완료되는 것을 확인했습니다.
- 저장소에 올라간 코드로 React 화면과 FastAPI 서버가 함께 실행되는 것을 확인했습니다.
- Azure 배포를 준비하면서 교육 계정의 GPU VM 할당량 제한을 확인하고, 추가 할당 가능 여부를 문의했습니다.

## 다음에 확인할 것

채팅에서 작성한 요청서를 문서함에 저장한 뒤, 로그아웃하고 다시 로그인해도 열 수 있는지 확인할 예정입니다. 두 계정으로 각각 대화와 문서를 저장해, 각 계정에 해당 계정의 기록만 표시되는지도 점검할 계획입니다.

## 소스 코드 바로 보기

- **[프론트엔드 전체 코드](./frontend)** · React, TypeScript
- **[백엔드 전체 코드](./backend)** · Python, FastAPI

| 코드 | 구현 내용 |
| --- | --- |
| [App.tsx](./frontend/src/App.tsx) | 메인 화면 구성과 채팅·문서함 화면 전환 |
| [style.css](./frontend/src/style.css) | 화면 배치, 색상, 버튼 등 공통 스타일 |
| [api.ts](./frontend/src/lib/api.ts) | 프론트엔드에서 백엔드 API를 호출하는 코드 |
| [main.py](./backend/app/main.py) | FastAPI 서버와 주요 API |
| [document_archive.py](./backend/app/document_archive.py) | 문서함의 저장·조회·삭제 로직 |

## 로컬 실행 방법 · Windows

### 01. 필요한 프로그램 설치

- [Node.js 다운로드](https://nodejs.org/en/download/)에서 **22.x**를 선택하고 Windows 설치 파일(`.msi`)을 실행합니다.
- [Python 3.12 Windows 설치 파일](https://www.python.org/downloads/release/python-31210/)에서 PC에 맞는 **Windows installer**를 내려받아 설치합니다.

설치가 끝나면 Windows에서 **명령 프롬프트(CMD)**를 새로 열고 아래 명령을 입력합니다. 각각 버전 번호가 나오면 다음 단계로 넘어갑니다.

```cmd
node -v
npm -v
py -3.12 --version
```

### 02. GitHub에서 코드 내려받기

1. 저장소 상단의 초록색 **Code** 버튼을 누르고 **Download ZIP**을 선택합니다.
2. ZIP 압축을 풉니다.
3. 파일 탐색기에서 **`frontend`와 `backend` 폴더가 함께 보이는 위치**로 들어갑니다.
4. 탐색기 주소창에 `cmd`를 입력하고 Enter를 눌러 해당 폴더에서 명령 프롬프트를 엽니다.

### 03. 화면 빌드와 서버 라이브러리 설치

위에서 연 CMD에 아래 명령을 순서대로 입력합니다. 처음에는 필요한 파일을 내려받으므로 몇 분 정도 걸릴 수 있습니다.

```cmd
set "VITE_API_BASE_URL=/"
npm --prefix frontend ci
npm --prefix frontend run build

cd backend
py -3.12 -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
```

### 04. Re AI 서버 실행

같은 CMD에서 아래 명령을 이어서 입력합니다.

```cmd
set "REAI_ENV=development"
set "REAI_CHAT_PROVIDER=mock"
set "REAI_DATA_DIR=..\data\readme-demo"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`Uvicorn running on http://127.0.0.1:8000`이 나오면 실행된 상태입니다. 체험하는 동안 이 창을 열어 두세요.

### 05. 브라우저에서 체험하기

**[Re AI 열기](http://127.0.0.1:8000)**를 누릅니다. 채팅창에 `PP 폐플라스틱 월 3톤 발생`을 입력하면 시연용 응답을 확인할 수 있습니다. 문서함에서는 테스트 파일을 업로드하고 다시 열어볼 수 있습니다.

로컬 시연에는 **로그인이나 API 키가 필요 없습니다.** 체험 데이터는 프로젝트의 `data/readme-demo/`에 저장됩니다. 실행을 종료하려면 CMD에서 **Ctrl+C**를 누릅니다.

다시 실행할 때는 파일 탐색기에서 `backend` 폴더를 열고, 주소창에 `cmd`를 입력한 뒤 **04번**부터 진행합니다.
