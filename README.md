# 📰 Seoul News AI Analyzer

### 실시간 뉴스 수집 · 분석 · 책임 있는 AI 리포트 생성 시스템

이 프로젝트는 서울신문 데이터를 기반으로  
"수집 → 임베딩 → 클러스터링 → AI 분석 → 리포트 생성"까지  
자동화한 **End-to-End 뉴스 분석 파이프라인**입니다.

---

### 🛠️ 기술 스택

| 분야 | 기술 |
|---|---|
| **Programming** | Python 3.10+, Gemini CLI, Cursor |
| **Backend** | FastAPI (추론 로직 처리) |
| **Database** | Qdrant (벡터 검색, 이슈 트래킹) |
| **AI/LLM** | GPT-5.4-mini, Tavily API (Fact-check & Context) |
| **Embedding** | text-embedding-3-small |
| **Frontend** | Streamlit (실시간 분석 대시보드) |
| **Pipeline** | GitHub Actions (주기적 배치 수집) |
| **Deploy** | Streamlit Cloud |

---

## 🧨 해결한 문제

### ❌ 기존 뉴스 요약 AI
- 단순 요약
- 상관관계 없음

### 🚀 프로젝트 핵심 가치

- 📊 **언론사 편집 의도를 데이터로 보존**
- 🤖 **LLM 기반 맥락 분석 (단순 요약 X)**
- 🔗 **아웃링크 구조로 트래픽 환원 (Responsible AI)**
- 🌐 **외부 데이터(Tavily) 기반 교차 검증**

---

## 🧠 주요 기능

### 1. 랭킹 기반 뉴스 수집
- 메인 Top / 카테고리 Top / 최신 뉴스 구분
- 단순 크롤링이 아닌 **편집 우선순위 반영 수집**

### 2. Smart Upsert (중복 처리 핵심)
- URL 기준 중복 제거
- 기존 데이터 유지 + 최신 정보만 갱신
- source priority 기반 병합

### 3. 벡터 기반 이슈 클러스터링
- OpenAI Embedding 활용
- cosine similarity 기반 기사 그룹화
- → **현재 이슈 구조 파악**

### 4. AI 리포트 생성
- GPT 기반 분석
- 단순 요약이 아닌:
  - Top News
  - 이슈 집중도 분석
  - 보도 맥락
  - 외부 정보 비교

### 5. 자동화된 오케스트레이션 (GitHub Actions)
- Daily Automation: GitHub Actions를 통해 매일 정해진 시각(KST 오전 9시)에 뉴스 수집 및 분석 파이프라인 자동 실행
- 환경 격리: Secrets를 활용한 보안 데이터 관리 및 자동화된 빌드/배포 환경(Ubuntu Runner) 구축
- 수동 실행 제어: workflow_dispatch 기능을 통한 필요시 즉각적인 파이프라인 재가동 지원

---

## 🧩 데이터 전략

### 🔥 소스 우선순위 (Ranking)

| 우선순위 | 소스 | 의미 |
|----------|------|------|
| 1 | `00_main_top` | 메인 핵심 |
| 2 | `01_top_...` | 카테고리 핵심 |
| 3 | `00_main_most` | 인기 기사 |
| 4 | `00_main_today` | 일반 기사 |
| 5 | `02_latest` | 최신 기사 |

---

### 🧠 Smart Merge 로직

기존 데이터 존재 시:
1. 기존 payload 유지
2. collected_at 최신화
3. latest_rank 업데이트
4. source_priority 비교 → 더 높은 우선순위 유지

---

### 🏗️ 시스템 아키텍처

<img width="1019" height="1150" alt="Image" src="https://github.com/user-attachments/assets/28c0f650-48b3-4306-abdd-929e5ab54a20" />
GPT 생성

---

### 🔍 AI 리포트 구조 (핵심 차별점)

실제 출력 예시:
🏆 서울신문 실시간 주요 이슈 분석: [카테고리]

🏆 Top News
1. ...
2. ...
3. ...

✍️ 기자들의 집중 보도 (비중순)
- 이슈별 기사 수 + 비중 분석
- 없으면 없다고 말함 (Hallucination 방지)

🌐 보도 맥락 분석
- 서울신문의 보도 방향 해석 및 외부 자료와 비교

📚 보충 리소스
- 외부 자료를 통한 뉴스 확장

🔮 최종 AI 인사이트
- 향후 전망 1문장

👉 핵심:
"무슨 일이 있었는가"가 아니라
"왜 이게 중요한가"까지 분석

---

### ⚖️ Responsible AI 설계
1. 저작권 보호
전문 복사 ❌
요약 + 링크 제공 ✅
2. 트래픽 환원 구조
모든 기사 → 원문 링크 연결
3. 정확성 확보
Tavily 기반 외부 검증

---

### 📂 폴더 구조

seoul_news/</br>
├── backend/            # 분석 및 LLM 추론 로직, DB 저장 (main.py, analyzer.py, database.py)</br>
├── frontend/           # 실시간 시각화 대시보드 (app.py)</br>
├── worker/             # 뉴스 수집기 (orchestrator.py, collector.py)</br>
├── .devcontainer/      # 개발 환경 표준화 설정</br>
├── .github/workflows   # 자동화 구축 (매일 아침 9시에 최신화 및 보고)</br>
└── README.md


---

### 🎯 시연 (Demo)

배포 링크 : https://seoulnews.streamlit.app/</br>

#### 실제 웹(Streamlit) 화면</br></br>

<img width="1540" height="951" alt="Image" src="https://github.com/user-attachments/assets/22b5175a-c746-48a7-9445-8add5febf7a4" />
</br></br>

#### 실제 Slack 보고 화면</br></br>

<img width="1401" height="1035" alt="Image" src="https://github.com/user-attachments/assets/6d08012e-861a-4df9-a26a-be80194b3b74" />


---

### 🚀 확장성 (Scalability)

☁️ AWS EC2 기반 배포 가능</br>
🐳 Docker 컨테이너화</br>
🔄 Airflow / GitHub Actions 기반 자동 수집 파이프라인</br>
📈 멀티 언론사 확장 가능 (조선/중앙 등)</br>
🧠 장기적으로 뉴스 트렌드 분석 및 예측 모델 확장 가능</br>