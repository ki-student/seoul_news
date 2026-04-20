import os
import json
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

class NewsAnalyzer:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.qdrant = QdrantClient(url=os.getenv("QDRANT_ENDPOINT"), api_key=os.getenv("QDRANT_API_KEY"), timeout=60)
        self.tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        self.collection_name = "seoul_news"
        self.model_name = "gpt-5.4-mini"
        self.snapshot_path = Path(__file__).resolve().parents[1] / "worker" / "seoul_news.json"
        self._ensure_payload_indexes()
        self.category_links = {
            "전체": "https://www.seoul.co.kr",
            "정치": "https://www.seoul.co.kr/news/newsList.php?section=politics",
            "경제": "https://www.seoul.co.kr/news/newsList.php?section=economy",
            "사회": "https://www.seoul.co.kr/news/newsList.php?section=society",
            "국제": "https://www.seoul.co.kr/news/newsList.php?section=international",
            "문화": "https://www.seoul.co.kr/news/newsList.php?section=life",
            "스포츠": "https://www.seoul.co.kr/newsList/sport/",
            "연예": "https://en.seoul.co.kr/news/newsList.php?section=entertainment",
            "정책.자치": "https://go.seoul.co.kr/"
        }

    def _ensure_payload_indexes(self):
        """Qdrant 컬렉션에 category 필터링을 위한 인덱스를 생성합니다."""
        try:
            self.qdrant.create_payload_index(
                collection_name=self.collection_name,
                field_name="category",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            print(f"✅ [{self.collection_name}] 'category' 인덱스 확인/생성 완료")
        except Exception as e:
            # 이미 인덱스가 있는 경우 에러가 날 수 있는데, 그건 무시해도 됩니다.
            pass

    def _get_korean_date(self):
        weekday_map = ['월', '화', '수', '목', '금', '토', '일']
        now = datetime.now()
        weekday = weekday_map[now.weekday()]
        return now.strftime(f"%Y년 %m월 %d일({weekday})")

    def _load_snapshot(self):
        with open(self.snapshot_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def fetch_articles(self, category):
        filter_condition = None
        if category != "전체":
            filter_condition = models.Filter(must=[models.FieldCondition(key="category", match=models.MatchValue(value=category))])
        else:
            filter_condition = models.Filter(should=[models.FieldCondition(key="category", match=models.MatchValue(value="00_메인"))])

        search_result = self.qdrant.scroll(collection_name=self.collection_name, scroll_filter=filter_condition, limit=1000, with_payload=True, with_vectors=False)
        points = search_result[0]
        snapshot = self._load_snapshot()
        articles = [p.payload for p in points]
        
        all_snapshot_articles = snapshot.get("articles", [])
        selected_indices = []
        for db_art in articles:
            for idx, snp_art in enumerate(all_snapshot_articles):
                if db_art.get('url') == snp_art.get('url'):
                    selected_indices.append(idx)
                    break
        return snapshot, selected_indices, articles

    def _build_issue_breakdown(self, snapshot, selected_index_set, article_by_index, total_count):
        clusters = snapshot.get("clusters", [])
        issue_rows = []
        for cluster in clusters:
            overlap = [idx for idx in cluster if idx in selected_index_set]
            if not overlap: continue
            rep_idx = overlap[0]
            rep = article_by_index.get(rep_idx, {})
            rep_title = rep.get("title", "대표 기사")
            issue_rows.append({
                "label": rep_title[:28] + ("..." if len(rep_title) > 28 else ""),
                "count": len(overlap),
                "ratio_pct": round((len(overlap) / total_count) * 100) if total_count else 0,
                "example_title": rep_title,
                "example_url": rep.get("url", "")
            })
        issue_rows.sort(key=lambda x: x["count"], reverse=True)
        return issue_rows[:3]

    def _get_external_info(self, category, topic):
        query = f"최근 {category} {topic} 관련 통계 및 배경 지식"
        try:
            search_res = self.tavily.search(query=query, search_depth="advanced", max_results=3)
            return "\n".join([f"• <{r['url']}|{r['title']}>" for r in search_res.get('results', [])])
        except: return "보충 정보를 가져올 수 없습니다."

    def analyze_category(self, target_category):
        snapshot, selected_indices, articles = self.fetch_articles(target_category)
        formatted_date = self._get_korean_date()

        if not articles:
            return {"report": f"[{target_category}] 데이터 부족", "viz_data": {"total_count": 0, "issue_breakdown": []}}

        # Top 기사 (00, 01 소스) 분류 및 랭킹 정렬
        top_articles = [a for a in articles if a.get("source", "").startswith(("00_", "01_"))]
        top_articles.sort(key=lambda x: x.get("latest_rank") or x.get("rank") or 99)
        top_articles = top_articles[:3]
        
        total_count = len(articles)
        article_by_index = {idx: article for idx, article in zip(selected_indices, articles)}
        issue_breakdown = self._build_issue_breakdown(snapshot, set(selected_indices), article_by_index, total_count)
        
        viz_data = {"total_count": total_count, "issue_breakdown": issue_breakdown, "date": formatted_date}
        top_issue_title = issue_breakdown[0]['example_title'] if issue_breakdown else articles[0]['title']
        ext_info = self._get_external_info(target_category, top_issue_title)
        
        header = f"🏆 *서울신문 실시간 주요 이슈 분석: [{target_category}]*\n_(분석 모델: {self.model_name})_\n\n---\n"

        top_titles_context = "\n".join([f"- {a['title']} (링크: {a['url']})" for a in top_articles[:5]]) or "- 중요 기사 없음"
        cluster_context = "\n".join([f"- {row['label']}: {row['count']}건 ({row['ratio_pct']}%), 대표기사: {row['example_title']}, 링크: {row['example_url']}" for row in issue_breakdown])

        prompt = f"""
        당신은 서울신문의 AI 분석 전문가입니다. 슬랙(Slack) 리포트를 작성하세요.
        오늘({formatted_date}) 수집된 데이터를 바탕으로 전문적인 리포트를 작성하세요.
        
        [1. 주요 뉴스 소스 (Top News)]
        {top_titles_context}

        [2. 집중 보도 이슈 (비중순)]
        {cluster_context}

        [외부 보충 정보]
        {ext_info}

        [작성 가이드라인]
        1. 각 섹션이 시작되기 전에 반드시 두 줄을 띄워 가독성을 높이세요. 모든 섹션 제목은 별표(*) 1개로 감싸서 굵게 표시하세요. (예: *🏆 섹션 제목*)

        2. '*🏆 Top News*': 
           - [1. 주요 뉴스 소스]를 바탕으로 간결하게 핵심 기사들을 리스트업하세요.
           - 반드시 1., 2., 3. 번호를 사용하되 있는 만큼만 사용하고 번호 사이 빈 줄(\\n\\n)을 넣으세요.
           - 각 항목은 [본문 설명 1줄] + [다음 줄에 링크 1줄(<URL|제목 🔗>)] 형태로 작성하세요. (링크는 서울신문 기사 링크로 작성하세요.)
           - 핵심 단어는 *굵게*(별표 1개) 표시하세요.

        3. '*✍️ 기자들의 집중 보도 (비중순)*': 
           - [2. 집중 보도 이슈] 데이터를 분석하되, 만약 기사 수가 2건 이상인 이슈가 하나도 없다면 다음과 같이 작성하세요: "현재 특정 이슈에 보도가 집중되지 않고 다양한 소식들이 고르게 다루어지고 있습니다." 
           - 2건 이상 묶인 이슈가 있는 경우에만, 전체 {total_count}건 중 차지하는 수치와 비중(%)을 명시하고 왜 이 이슈가 뜨거운 감자인지 브리핑하세요.
           - 각 항목은 [본문 설명 1줄] + [다음 줄에 링크 1줄(<URL|제목 🔗>)] 형태로 작성하세요. (링크는 서울신문 기사 링크로 작성하세요.)
           - 핵심 단어는 *굵게*(별표 1개) 표시하세요.

        4. '🌐 보도 맥락 분석': 
           - 서울신문이 현재 이 카테고리에서 다른 매체와 비교했을 때 어떤 방향으로 보도하고 있는지 분석하세요.
           - 특정 사건에 편중되어 있는지, 혹은 다양한 주제를 고르게 다루고 있는지 설명하세요.
           - 서울신문의 보도 방향성과 톤을 분석하여 2~3줄로 요약하세요.

        5. '📚 보충 리소스': 
           - 제공된 외부 리소스를 활용하여 독자가 함께 읽으면 좋은 정보를 큐레이션하세요.

        6. '🔮 최종 AI 인사이트': 
           - 오늘 {target_category} 분야 보도를 종합하여, 기자가 주목해야 할 핵심 포인트나 향후 전망을 한 문장으로 제시하세요.
        """

        try:
            res = self.client.chat.completions.create(model=self.model_name, messages=[{"role": "user", "content": prompt}], temperature=0.2)
            report_body = res.choices[0].message.content
        except: report_body = "리포트 생성 중 오류가 발생했습니다."

        other_links = [f"• <{url}|{cat} 🔗>" for cat, url in self.category_links.items() if cat != target_category]
        footer = "\n\n---\n*🔽 다른 카테고리 소식 더 보러가기*\n" + "  ".join(other_links)
        
        return {"report": f"{header}\n{report_body}{footer}", "viz_data": viz_data}
