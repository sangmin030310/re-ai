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

## 로컬 실행 방법

**실행 환경** · Git, Node.js 22, Python 3.12  
아래 명령은 Windows **CMD** 기준입니다. VS Code를 사용한다면 터미널에서 **Command Prompt**를 선택하세요.

### 1. 코드 내려받기

```cmd
git clone https://github.com/sangmin030310/re-ai.git
cd re-ai
```

이미 내려받았다면 `re-ai` 폴더에서 2번부터 진행합니다.

### 2. 프론트엔드 빌드하기

```cmd
set "VITE_API_BASE_URL=/"
npm --prefix frontend ci
npm --prefix frontend run build
```

### 3. FastAPI 서버 실행하기

같은 터미널에서 이어서 실행합니다.

```cmd
cd backend
py -3.12 -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt

set "REAI_ENV=development"
set "REAI_CHAT_PROVIDER=mock"
set "REAI_DATA_DIR=..\data\readme-demo"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4. 브라우저에서 확인하기

서버가 시작되면 **[Re AI 열기](http://127.0.0.1:8000)**를 누릅니다. 채팅창에 `PP 폐플라스틱 월 3톤 발생`을 입력하면 시연용 응답을 확인할 수 있습니다.

로컬 시연 모드는 로그인이나 API 키 없이 사용할 수 있으며, 시연 중 저장한 데이터는 `data/readme-demo/`에 보관됩니다. 종료할 때는 터미널에서 **Ctrl+C**를 누릅니다.
