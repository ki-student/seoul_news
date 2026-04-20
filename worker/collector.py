import requests
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urljoin
import time
from datetime import datetime, timedelta
import json
import os
import hashlib
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity
from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

load_dotenv()

def log(msg):
    print(f"[LOG] {msg}")

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
BASE_URL = "https://www.seoul.co.kr/"

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536

# Qdrant 클라이언트 설정 (timeout 추가)
qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_ENDPOINT"),
    api_key=os.getenv("QDRANT_API_KEY"),
    timeout=60 
)
COLLECTION_NAME = "seoul_news"

def get_embeddings(texts):
    """OpenAI 모델을 사용하여 텍스트 임베딩 생성"""
    try:
        response = client.embeddings.create(
            input=texts,
            model=EMBEDDING_MODEL
        )
        return [data.embedding for data in response.data]
    except Exception as e:
        log(f"임베딩 생성 에러: {e}")
        return None
def init_qdrant_collection():
    """뉴스 컬렉션 초기화"""
    try:
        collections = qdrant_client.get_collections().collections
        exists = any(c.name == COLLECTION_NAME for c in collections)
        if not exists:
            log(f"Qdrant 컬렉션 '{COLLECTION_NAME}' ({VECTOR_SIZE}차원) 생성 중...")
            qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
            )
            log(f"✅ 컬렉션 '{COLLECTION_NAME}' 생성 완료.")

        # [추가] 수집 시간 필드에 숫자 인덱스 생성 (삭제 기능을 위해 필수)
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="collected_at",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
    except Exception as e:
        # 이미 인덱스가 있는 경우 등의 사소한 에러는 무시
        pass

# =====================================================
# 🔹 데이터 정제 및 유틸리티
# =====================================================

def get_safe_title(a_tag):
    if not a_tag: return ""
    title_target = a_tag.select_one('strong, .tit, .title, span, h2, h3')
    text = title_target.get_text(strip=True) if title_target else a_tag.get_text(strip=True)
    return text if len(text) > 1 else ""

def extract_text(tag):
    if not tag: return ""
    for s in tag(['script', 'style', 'button', 'iframe', 'ins']):
        s.decompose()
    
    blacklist = ['v_photo', 'expendImageWrap', 'img_area', 'spotlightBox', 'view_img_caption', 'btn_view_origin', 'copyright']
    texts = []
    for node in tag.find_all(string=True):
        if isinstance(node, NavigableString):
            parent_classes = []
            for p in node.parents:
                if p == tag: break
                parent_classes.extend(p.get('class', []))
            if any(cls in blacklist for cls in parent_classes): continue
            clean_text = node.strip()
            if not clean_text or clean_text.startswith('$(') or 'function()' in clean_text: continue
            if 'Copyright' in clean_text or '무단 전재' in clean_text: continue
            if len(clean_text) > 2:
                texts.append(clean_text)
    return "\n".join(texts).strip()

# =====================================================
# 🔹 섹션별 수집 엔진
# =====================================================

def crawl_main():
    log("메인 페이지 수집 중...")
    res = requests.get(BASE_URL, headers=headers)
    res.encoding = 'utf-8'
    soup = BeautifulSoup(res.text, "html.parser")
    articles = []
    for i, a in enumerate(soup.select(".main-top-layout a")):
        title = get_safe_title(a)
        if title and len(title) > 5:
            articles.append({"title": title, "url": urljoin(BASE_URL, a.get("href")), "source": "00_main_top", "category": "00_메인", "rank": i + 1})
    for i, a in enumerate(soup.select(".articleContentWrap a")):
        title = get_safe_title(a)
        if title and len(title) > 5:
            articles.append({"title": title, "url": urljoin(BASE_URL, a.get("href")), "source": "00_main_today", "category": "00_메인", "rank": i + 1})
    for i, li in enumerate(soup.select("div.sectionContentWrap ol li")[:10]):
        a = li.select_one("a")
        if a:
            title = get_safe_title(a)
            if title: articles.append({"title": title, "url": urljoin(BASE_URL, a.get("href")), "source": "00_main_most", "category": "00_메인", "rank": i + 1})
    return articles

def crawl_category_page(category_name, url):
    res = requests.get(url, headers=headers)
    res.encoding = 'utf-8'
    soup = BeautifulSoup(res.text, "html.parser")
    articles = []
    for i, li in enumerate(soup.select("div.sectionContentWrap ol li")[:5]):
        a = li.select_one("a")
        if a:
            title = get_safe_title(a)
            if title: articles.append({"title": title, "url": urljoin(BASE_URL, a.get("href")), "source": "01_top_popular", "category": category_name, "rank": i + 1})
    list_area = soup.select_one("div.listMain")
    if list_area:
        for paging in list_area.select(".pagination, .paging, .page"): paging.decompose()
        for i, li in enumerate(list_area.select("section ul li")):
            title_link = li.select_one(".articleTitle a") or li.select_one("a")
            if title_link:
                title = get_safe_title(title_link).strip()
                if not title or len(title) < 5 or "page=" in title_link.get("href"): continue
                articles.append({"title": title, "url": urljoin(BASE_URL, title_link.get("href")), "source": "02_latest", "category": category_name, "rank": i + 1})
    return articles

def crawl_policy():
    url = "https://go.seoul.co.kr/"
    res = requests.get(url, headers=headers)
    res.encoding = 'cp949'
    soup = BeautifulSoup(res.text, "html.parser")
    articles = []
    for i, item in enumerate(soup.select("#hitTab01 ol li, .bestview ul li a")[:10]):
        a = item if item.name == 'a' else item.select_one('a')
        if a:
            title = get_safe_title(a)
            if title and len(title) > 2:
                articles.append({"title": title, "url": urljoin(url, a.get("href")), "source": "01_policy_top_best", "category": "정책.자치", "rank": i + 1})
    sector_names = ["정책.행정", "지방자치", "서울"]
    for i in range(3):
        for j, a in enumerate(soup.select(f"#main_news_{i} li a") + soup.select(f"#main_news2_{i} li a")):
            title = get_safe_title(a)
            if title:
                articles.append({"title": title, "url": urljoin(url, a.get("href")), "source": f"02_policy_sector_{i+1}", "category": "정책.자치", "sub_category": sector_names[i], "rank": j + 1})
    return articles

def crawl_entertainment():
    url = "https://en.seoul.co.kr/news/newsList.php?section=entertainment"
    res = requests.get(url, headers=headers)
    res.encoding = 'utf-8'
    soup = BeautifulSoup(res.text, "html.parser")
    articles = []
    for i, a in enumerate(soup.select('main > section > div > div > div:nth-child(1) a')[:4]):
        title = get_safe_title(a)
        if title: articles.append({"title": title, "url": urljoin("https://en.seoul.co.kr", a.get("href")), "source": "01_ent_top", "category": "연애", "rank": i + 1})
    for i, li in enumerate(soup.select('section.main-left > div > ul > li')[:20]):
        a = li.select_one('a')
        if a:
            title = get_safe_title(a)
            if title: articles.append({"title": title, "url": urljoin("https://en.seoul.co.kr", a.get("href")), "source": "02_ent_latest", "category": "연애", "rank": i + 1})
    return articles

# =====================================================
# 🔹 Qdrant 업로드 및 클라우드 정리 로직
# =====================================================

def cleanup_old_articles():
    """24시간(1일) 이상 지난 기사 삭제"""
    cutoff_time = int((datetime.now() - timedelta(days=1)).timestamp())
    try:
        log(f"오래된 기사 정리 중 (기준: 24시간 전)...")
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="collected_at",
                        range=models.Range(lt=cutoff_time)
                    )
                ]
            )
        )
    except Exception as e:
        log(f"데이터 정리 중 에러: {e}")

def process_and_upload(articles):
    log(f"데이터 처리 및 Qdrant 업로드 시작 (총 {len(articles)}개)...")
    init_qdrant_collection()
    
    current_time = int(time.time())
    
    # 1. Qdrant 업로드 및 데이터 병합
    points = []
    skipped_count = 0
    
    for i, article in enumerate(articles):
        point_id = hashlib.md5(article["url"].encode()).hexdigest()
        
        # 기존 데이터 조회 (벡터 포함)
        existing = qdrant_client.retrieve(collection_name=COLLECTION_NAME, ids=[point_id], with_vectors=True)
        
        if existing and existing[0].vector:
            skipped_count += 1
            existing_point = existing[0]
            article_payload = existing_point.payload
            # 랭크와 수집 시간만 최신으로 갱신
            article_payload.update({
                "collected_at": current_time,
                "latest_rank": article.get("rank", 0)
            })
            points.append(models.PointStruct(id=point_id, vector=existing_point.vector, payload=article_payload))
        else:
            # 새로운 기사 혹은 벡터가 없는 기사는 임베딩 다시 수행
            embedding = get_embeddings([article["title"]])[0]
            article["collected_at"] = current_time
            article["latest_rank"] = article.get("rank", 0)
            points.append(models.PointStruct(id=point_id, vector=embedding, payload=article))
        
        if len(points) >= 50:
            qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
            points = []
            
    if points:
        qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    
    cleanup_old_articles()
    log(f"✅ Qdrant 업로드 완료. (중복 건너뜀: {skipped_count}건)")

    # 2. 클러스터링을 위한 임베딩 데이터 수집
    # (클러스터링을 위해서는 전체 벡터가 필요하므로 간단히 스크롤 활용)
    log("유사 기사 그룹화 중...")
    scroll_res = qdrant_client.scroll(collection_name=COLLECTION_NAME, limit=1000, with_vectors=True)
    points = scroll_res[0]
    
    clusters = []
    for i, p in enumerate(points):
        added = False
        for c in clusters:
            sim = cosine_similarity([p.vector], [points[c[0]].vector])[0][0]
            if sim > 0.8:
                c.append(i)
                added = True
                break
        if not added: clusters.append([i])
    return clusters

# =====================================================
# 🔹 메인 실행 로직
# =====================================================

CATEGORY_URLS = {
    "정치": "https://www.seoul.co.kr/news/newsList.php?section=politics",
    "경제": "https://www.seoul.co.kr/news/newsList.php?section=economy",
    "사회": "https://www.seoul.co.kr/news/newsList.php?section=society",
    "국제": "https://www.seoul.co.kr/news/newsList.php?section=international",
    "문화": "https://www.seoul.co.kr/news/newsList.php?section=life",
    "스포츠": "https://www.seoul.co.kr/newsList/sport/"
}

def run_total_pipeline():
    all_raw_data = []
    all_raw_data.extend(crawl_main())
    all_raw_data.extend(crawl_policy())
    all_raw_data.extend(crawl_entertainment())
    for name, url in CATEGORY_URLS.items():
        all_raw_data.extend(crawl_category_page(name, url))

    # 소스별 우선순위 설정 (낮을수록 우선순위 높음)
    source_priority = {
        # 1순위: 전체 메인 Top (압도적 중요도)
        "00_main_top": 1,

        # 2순위: 카테고리별 핵심 (카테고리 내에서 중요)
        "01_top_popular": 2, "01_policy_top_best": 2, "01_ent_top": 2,

        # 3순위: 독자 반응 (관심도)
        "00_main_most": 3,

        # 4순위: 메인 일반
        "00_main_today": 4,

        # 5순위: 나머지는 최신순
        "02_latest": 5, "02_policy_sector_1": 5, "02_policy_sector_2": 5, 
        "02_policy_sector_3": 5, "02_ent_latest": 5
    }
    
    unique_data = {}
    for a in all_raw_data:
        url = a["url"]
        if url not in unique_data:
            unique_data[url] = a
        else:
            # 이미 있으면 우선순위가 더 높은 것만 유지
            current_priority = source_priority.get(a["source"], 99)
            existing_priority = source_priority.get(unique_data[url]["source"], 99)
            if current_priority < existing_priority:
                unique_data[url] = a

    final_list = list(unique_data.values())
    final_list.sort(key=lambda x: (x.get("category", "ZZ"), x.get("source", "ZZ")))

    log(f"정렬 완료. 고유 기사 {len(final_list)}개 본문 수집 시작...")
    for i, a in enumerate(final_list):
        try:
            res = requests.get(a["url"], headers=headers, timeout=10)
            
            # [핵심 수정] 인코딩 깨짐을 방지하기 위해 UTF-8 ignore 방식으로 디코딩
            html_text = res.content.decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html_text, "html.parser")
            
            # [추가] 정책.자치 기사인 경우 기사 페이지의 정확한 위치에서 제목 재추출
            if a.get("category") == "정책.자치":
                title_tag = soup.select_one("#container > div.content > div.atic_title > h3")
                if title_tag:
                    a["title"] = title_tag.get_text(strip=True)

            tag = soup.select_one("#articleContent .viewContent, .viewContent, #article_content, .articleBody")
            a["content"] = extract_text(tag)
            if i % 30 == 0: log(f"진행: {i}/{len(final_list)}")
        except Exception as e:
            a["content"] = ""
        time.sleep(0.05)

    # 데이터 업로드 및 클러스터링
    clusters = process_and_upload(final_list) # Qdrant 업로드 재활성화

    # JSON 저장
    output = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "articles": final_list, "clusters": clusters or []}
    with open("seoul_news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log("작업 완료: 'seoul_news.json' 저장 및 Qdrant 업로드 완료.")

if __name__ == "__main__":
    run_total_pipeline()