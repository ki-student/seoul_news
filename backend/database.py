# to vectorDB

import os
import json
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.http import models
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_ENDPOINT"),
    api_key=os.getenv("QDRANT_API_KEY"),
)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

COLLECTION_NAME = "seoul_news"

def get_unique_id(url):
    """URL을 고유한 정수 ID로 변환하여 중복 방지"""
    return int(hashlib.md5(url.encode('utf-8')).hexdigest(), 16) % (10**15)

def init_qdrant():
    """콜렉션 체크 및 생성"""
    collections = qdrant_client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    
    if not exists:
        print(f"[DB] '{COLLECTION_NAME}' 콜렉션을 새로 생성합니다...")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
        )
    else:
        print(f"[DB] '{COLLECTION_NAME}' 콜렉션이 이미 존재합니다. 동기화를 진행합니다.")

def upload_news_to_qdrant(file_path):
    """JSON 데이터를 클러스터 정보와 함께 적재"""
    if not os.path.exists(file_path):
        print(f"[ERROR] 파일을 찾을 수 없습니다: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    articles = data.get("articles", [])
    clusters_list = data.get("clusters", [])
    total_count = len(articles)
    
    if total_count == 0:
        print("[DB] 적재할 기사가 없습니다.")
        return

    # 1. 클러스터 매핑 생성 (인덱스 -> 클러스터ID)
    index_to_cluster = {}
    for cluster_id, article_indices in enumerate(clusters_list):
        for idx in article_indices:
            index_to_cluster[idx] = cluster_id

    # 2. 기존 ID 목록 가져오기 (중복 체크용)
    existing_points, _ = qdrant_client.scroll(
        collection_name=COLLECTION_NAME, limit=10000, with_payload=False
    )
    existing_ids = {p.id for p in existing_points}

    points = []
    new_count = 0
    
    print(f"[DB] 총 {total_count}개의 데이터 처리 시작 (클러스터 정보 포함)...")

    for i, article in enumerate(articles):
        point_id = get_unique_id(article.get('url', article['title']))
        
        # 신규 여부 체크
        if point_id not in existing_ids:
            new_count += 1
            
        # 3. 클러스터 ID 주입 및 Payload 구성
        payload = article.copy()
        payload["cluster_id"] = index_to_cluster.get(i, -1) # 해당 인덱스의 클러스터 ID 부여
        
        # 임베딩 생성
        text_to_embed = f"{article['title']}\n{article['content']}"
        response = openai_client.embeddings.create(
            input=text_to_embed,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding
        
        points.append(models.PointStruct(
            id=point_id,
            vector=embedding,
            payload=payload
        ))
        
        # 20개 단위 로그
        if (i + 1) % 20 == 0 or (i + 1) == total_count:
            print(f"[DB] 진행 상황: {i + 1}/{total_count} 완료...")

    # 4. 서버 업로드
    if points:
        qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    
    print("\n" + "="*30)
    print(f"🚀 [DB 적재 완료 보고서]")
    print(f"- 전체 처리 기사: {total_count}건")
    print(f"- 신규 추가 기사: {new_count}건")
    print(f"- 업데이트(중복): {total_count - new_count}건")
    print(f"- 클러스터 매핑 완료")
    print("="*30 + "\n")

if __name__ == "__main__":
    init_qdrant()
    json_path = "../worker/seoul_news.json" 
    upload_news_to_qdrant(json_path)