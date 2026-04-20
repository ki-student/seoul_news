import os
import json
from datetime import datetime
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
        self.category_links = {
            "전체": "https://www.seoul.co.kr",
            "정치": "https://www.seoul.co.kr/news/newsList.php?section=politics",
            "경제": "https://www.seoul.co.kr/news/newsList.php?section=economy",
            "사회": "https://www.seoul.co.kr/news/newsList.php?section=society",
            "국제": "https://www.seoul.co.kr/news/newsList.php?section=international",
            "문화": "https://www.seoul.co.kr/news/newsList.php?section=life",
            "스포츠": "https://www.seoul.co.kr/newsList/sport/",
            "연애": "https://en.seoul.co.kr/news/newsList.php?section=entertainment",
            "정책.자치": "https://go.seoul.co.kr/"
        }

    def _get_korean_date(self):
        weekday_map = ['월', '화', '수', '목', '금', '토', '일']
        now = datetime.now()
        return now.strftime(f"%Y년 %m월 %d일({weekday_map[now.weekday()]})")

    def fetch_articles(self, category):
        filter_condition = models.Filter(must=[models.FieldCondition(key="category", match=models.MatchValue(value=category))]) if category != "전체" \
                           else models.Filter(should=[models.FieldCondition(key="category", match=models.MatchValue(value="00_메인"))])
        
        search_result = self.qdrant.scroll(collection_name=self.collection_name, scroll_filter=filter_condition, limit=1000, with_payload=True, with_vectors=False)
        return [p.payload for p in search_result[0]]

    def _get_external_info(self, category, topic):
        query = f"최근 {category} {topic} 관련 통계 및 배경 지식"
        try:
            search_res = self.tavily.search(query=query, search_depth="advanced", max_results=3)
            return "\n".join([f"• <{r['url']}|{r['title']}>" for r in search_res.get('results', [])])
        except: return "보충 정보를 가져올 수 없습니다."

    def analyze_category(self, target_category):
        articles = self.fetch_articles(target_category)
        formatted_date = self._get_korean_date()

        if not articles:
            return {"report": f"[{target_category}] 데이터 부족", "viz_data": {"total_count": 0}}

        top_articles = sorted([a for a in articles if a.get("source", "").startswith(("00_", "01_"))], 
                             key=lambda x: x.get("latest_rank") or x.get("rank") or 99)[:3]
        
        total_count = len(articles)
        
        top_titles_context = "\n\n".join([f"{i+1}. *{a['title']}*\n{a['url']}" for i, a in enumerate(top_articles)]) if top_articles else "- 중요 기사 없음"
        ext_info = self._get_external_info(target_category, top_articles[0]['title'] if top_articles else target_category)

        prompt = f"""
        당신은 서울신문의 AI 분석 전문가입니다. 아래 가이드라인에 맞춰 전문적인 리포트를 작성하세요.
        
        [필수 정보]
        - 보고 일자: {formatted_date}
        - 타겟 카테고리: {target_category}
        - 분석 기사 수: {total_count}건

        [작성 가이드라인]
        1. 모든 섹션 제목은 별표(*) 1개로 감싸 굵게 표시하세요. (예: *🏆 섹션 제목*)
        2. 기사 링크는 제목과 함께 표기하지 말고, 본문 아래 줄에 따로 작성하세요.
        
        *🏆 Top News*
        {top_titles_context}

        *✍️ 기자들의 집중 보도*
        현재 다양한 주요 소식들이 비중 있게 다루어지고 있습니다.

        *🌐 보도 맥락 분석*
        서울신문의 현재 {target_category} 보도 방향성과 톤을 분석하여 2~3줄로 요약하세요.

        *📚 보충 리소스*
        {ext_info}

        *🔮 최종 AI 인사이트*
        오늘 {target_category} 보도를 종합하여, 향후 기자가 주목해야 할 핵심 포인트나 향후 전망을 한 문장으로 제시하세요.
        """

        try:
            res = self.client.chat.completions.create(model=self.model_name, messages=[{"role": "user", "content": prompt}], temperature=0.2)
            report_body = res.choices[0].message.content
        except: report_body = "리포트 생성 중 오류가 발생했습니다."

        other_links = [f"• <{url}|{cat} 🔗>" for cat, url in self.category_links.items() if cat != target_category]
        footer = "\n\n---\n*🔽 다른 카테고리 소식 더 보러가기*\n" + "  ".join(other_links)
        
        return {"report": f"🏆 *서울신문 실시간 주요 이슈 분석: [{target_category}]*\n_(분석 모델: {self.model_name})_\n\n---\n{report_body}{footer}", "viz_data": {"total_count": total_count}}
