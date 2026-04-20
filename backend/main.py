import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

# 원준님이 만드신 분석 엔진 임포트
from analyzer import NewsAnalyzer

app = FastAPI()
analyzer = NewsAnalyzer()

# Qdrant 설정
qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_ENDPOINT"),
    api_key=os.getenv("QDRANT_API_KEY")
)
USER_COLLECTION = "user_profiles"

def init_user_db():
    """사용자 프로필 컬렉션 초기화"""
    try:
        collections = qdrant_client.get_collections().collections
        exists = any(c.name == USER_COLLECTION for c in collections)
        if not exists:
            # 사용자 정보는 메타데이터(payload) 위주이므로 작은 벡터 하나를 생성합니다.
            qdrant_client.create_collection(
                collection_name=USER_COLLECTION,
                vectors_config=models.VectorParams(size=128, distance=models.Distance.COSINE),
            )
            print(f"✅ Qdrant 컬렉션 '{USER_COLLECTION}' 생성 완료")
    except Exception as e:
        print(f"❌ Qdrant 초기화 에러: {e}")

init_user_db()

# --- [2. 데이터 모델 정의] ---
class UserProfile(BaseModel):
    username: str
    slack_webhook: str
    interests: str

class LoginRequest(BaseModel):
    username: str

# --- [3. API 엔드포인트] ---

@app.post("/register_or_update")
def register_user(user: UserProfile):
    """회원가입 및 정보 수정 (Qdrant 저장)"""
    try:
        qdrant_client.upsert(
            collection_name=USER_COLLECTION,
            points=[
                models.PointStruct(
                    id=user.username, # 아이디를 고유 ID로 사용
                    vector=[0.0] * 128, # 더미 벡터
                    payload={
                        "username": user.username,
                        "slack_webhook": user.slack_webhook,
                        "interests": user.interests
                    }
                )
            ]
        )
        return {"message": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login")
def login(req: LoginRequest):
    """로그인: Qdrant에서 유저 정보 검색"""
    try:
        result = qdrant_client.retrieve(
            collection_name=USER_COLLECTION,
            ids=[req.username]
        )
        if result:
            user_data = result[0].payload
            return user_data
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze")
async def do_analysis(username: str, category: str):
    """분석 실행 및 해당 유저의 슬랙으로 전송"""
    # 1. AI 분석 수행
    result = analyzer.analyze_category(category)
    
    # 2. Qdrant에서 이 유저의 슬랙 웹훅 주소 가져오기
    try:
        user_res = qdrant_client.retrieve(
            collection_name=USER_COLLECTION,
            ids=[username]
        )
        if user_res:
            webhook_url = user_res[0].payload.get("slack_webhook")
            # 3. 슬랙으로 리포트 쏘기
            if webhook_url and webhook_url.startswith("https://hooks.slack.com"):
                payload = {"text": result['report']}
                requests.post(webhook_url, json=payload)
                print(f"✅ {username}님 슬랙 전송 완료")
    except Exception as e:
        print(f"❌ 슬랙 전송 과정에서 에러 발생: {e}")

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)