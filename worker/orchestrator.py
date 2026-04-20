import os
import sys
import requests
from dotenv import load_dotenv

# 상위 디렉토리 및 백엔드 디렉토리를 경로에 추가하여 임포트 가능하게 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "backend"))

from worker.collector import run_total_pipeline
from backend.analyzer import NewsAnalyzer
from qdrant_client import QdrantClient

load_dotenv()

def run_daily_orchestration():
    print("🚀 [1/4] 뉴스 데이터 수집 및 Qdrant 업데이트 시작...")
    run_total_pipeline()

    print("\n🚀 [2/4] 분석 엔진 및 DB 연결 초기화...")
    analyzer = NewsAnalyzer()
    qdrant_client = QdrantClient(
        url=os.getenv("QDRANT_ENDPOINT"),
        api_key=os.getenv("QDRANT_API_KEY")
    )
    
    # Qdrant에서 모든 사용자 정보 가져오기
    print("🚀 [3/4] 사용자 목록 조회 중...")
    try:
        # scroll을 사용해 모든 유저 페이로드 가져오기
        users_result = qdrant_client.scroll(
            collection_name="user_profiles",
            limit=100,
            with_payload=True,
            with_vectors=False
        )
        users = [p.payload for p in users_result[0]]
    except Exception as e:
        print(f"⚠️ 유저 목록 조회 실패 (컬렉션이 없을 수 있음): {e}")
        users = []

    # 관리자 백업 (유저가 없거나 시연용)
    admin_webhook = os.getenv("ADMIN_SLACK_WEBHOOK") or os.getenv("SLACK_WEBHOOK_URL")
    
    if not users and admin_webhook:
        print("ℹ️ 등록된 사용자가 없습니다. 관리자용 기본 전송을 수행합니다.")
        users = [{
            "username": "관리자",
            "slack_webhook": admin_webhook,
            "interests": "전체"
        }]

    print(f"\n🚀 [4/4] 총 {len(users)}명의 사용자에게 분석 리포트 전송 시작...")
    for user in users:
        username = user.get("username", "알 수 없음")
        interests = user.get("interests", "전체")
        webhook = user.get("slack_webhook")
        
        if not webhook or not webhook.startswith("http"):
            print(f"⏩ {username}님: 유효한 슬랙 웹훅이 없어 건너뜁니다.")
            continue

        print(f"📦 {username}님({interests}) 리포트 생성 중...")
        try:
            # analyzer.py의 analyze_category 함수 활용
            result = analyzer.analyze_category(interests)
            
            # 슬랙 전송
            payload = {"text": result['report']}
            response = requests.post(webhook, json=payload)
            
            if response.status_code == 200:
                print(f"✅ {username}님께 슬랙 전송 성공!")
            else:
                print(f"❌ {username}님 슬랙 전송 실패 (Status: {response.status_code})")
        except Exception as e:
            print(f"❌ {username}님 리포트 전송 에러: {e}")

    print("\n✨ 모든 자동화 작업이 완료되었습니다.")

if __name__ == "__main__":
    run_daily_orchestration()