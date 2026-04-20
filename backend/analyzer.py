import os
import json
from datetime import datetime
from collections import Counter
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
        self.qdrant = QdrantClient(url=os.getenv("QDRANT_ENDPOINT"), api_key=os.getenv("QDRANT_API_KEY"))
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
            "연애": "https://en.seoul.co.kr/news/newsList.php?section=entertainment",
            "정책.자치": "https://go.seoul.co.kr/"
        }

    def _get_korean_date(self):
        weekday_map = ['월', '화', '수', '목', '금', '토', '일']
        now = datetime.now()
        weekday = weekday_map[now.weekday()]
        return now.strftime(f"%Y년 %m월 %d일({weekday})")

    def _ensure_payload_indexes(self):
        """필터에 사용하는 payload 필드 인덱스를 보장합니다."""
        for field_name in ("source", "category"):
            try:
                self.qdrant.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                # 이미 존재하거나 서버 상태상 생성이 불필요한 경우는 무시
                pass

    def _load_snapshot(self):
        with open(self.snapshot_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _is_target_category(self, article, category):
        if category == "전체":
            source = article.get("source", "")
            return source.startswith("00_main_") or article.get("category") == "00_메인"
        return article.get("category") == category

    def fetch_articles(self, category):
        """Qdrant에서 해당 카테고리의 모든 데이터를 가져옵니다."""
        filter_condition = None
        if category != "전체":
            filter_condition = models.Filter(
                must=[models.FieldCondition(key="category", match=models.MatchValue(value=category))]
            )
        else:
            # '전체'일 경우 메인 섹션 데이터 위주로 필터링
            filter_condition = models.Filter(
                should=[
                    models.FieldCondition(key="category", match=models.MatchValue(value="00_메인"))
                ]
            )

        # limit을 없애거나 매우 크게 설정하여 저장된 데이터를 최대한 가져옴
        search_result = self.qdrant.scroll(
            collection_name=self.collection_name,
            scroll_filter=filter_condition,
            limit=1000, # 사실상 저장된 전량을 의미
            with_payload=True,
            with_vectors=False
        )
        
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
            if not overlap:
                continue
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
        top3 = issue_rows[:3]

        # clusters가 비어있거나 매칭이 적은 경우 제목 빈도로 보강
        if len(top3) < 3:
            used_titles = {row["example_title"] for row in top3}
            for article in article_by_index.values():
                title = article.get("title", "")
                if not title or title in used_titles:
                    continue
                top3.append({
                    "label": title[:28] + ("..." if len(title) > 28 else ""),
                    "count": 1,
                    "ratio_pct": round((1 / total_count) * 100) if total_count else 0,
                    "example_title": title,
                    "example_url": article.get("url", "")
                })
                if len(top3) == 3:
                    break
        return top3

    def _get_external_info(self, category, topic):
        query = f"최근 {category} {topic} 관련 통계 및 배경 지식"
        try:
            search_res = self.tavily.search(query=query, search_depth="advanced", max_results=3)
            return "\n".join([f"• <{r['url']}|{r['title']}>" for r in search_res.get('results', [])])
        except:
            return "보충 정보를 가져올 수 없습니다."

    def analyze_category(self, target_category):
        snapshot, selected_indices, articles = self.fetch_articles(target_category)
        formatted_date = self._get_korean_date()

        if not articles:
            return {
                "report": f"[{target_category}] 데이터 부족",
                "viz_data": {
                    "total_count": 0,
                    "top_keywords": {},
                    "keyword_text": "",
                    "issue_breakdown": []
                }
            }

        total_count = len(articles)
        article_by_index = {
            idx: article for idx, article in zip(selected_indices, articles)
        }
        issue_breakdown = self._build_issue_breakdown(
            snapshot=snapshot,
            selected_index_set=set(selected_indices),
            article_by_index=article_by_index,
            total_count=total_count
        )
        singleton_count = total_count - sum([row["count"] for row in issue_breakdown])
        viz_data = {
            "total_count": total_count,
            "top_keywords": dict(Counter([row["label"] for row in issue_breakdown]).most_common(5)),
            "keyword_text": ", ".join([row["label"] for row in issue_breakdown]),
            "issue_breakdown": issue_breakdown,
            "singleton_count": max(0, singleton_count),
            "date": formatted_date
        }
        ext_info = self._get_external_info(target_category, articles[0]['title'])
        
        header = (
            f"🏆 *서울신문 실시간 주요 이슈 분석: [{target_category}]*\n"
            f"_(기준 데이터: 최신 기사 {viz_data['total_count']}건 / 분석 모델: {self.model_name})_\n\n"
            f"---"
        )

        cluster_context = "\n".join([
            f"- {row['label']}: {row['count']}건 ({row['ratio_pct']}%), 대표기사: {row['example_title']}, 링크: {row['example_url']}"
            for row in issue_breakdown
        ]) or "- 다중 기사 클러스터(2건 이상)가 아직 충분하지 않습니다."

        # 모델 입력 토큰을 줄이기 위해 클러스터 요약 + 제목 일부만 전달
        title_context = "\n".join([f"- {a.get('title', '')}" for a in articles[:200]])

        prompt = f"""
        당신은 서울신문의 AI 분석 전문가입니다.
        오늘({formatted_date}) 수집된 데이터를 바탕으로 전문적인 리포트를 작성하세요.
        
        [내부 보도 통계]
        - 보고 일자: {formatted_date}
        - 수집된 기사 총 수: {viz_data['total_count']}건
        - 핵심 이슈: {viz_data['keyword_text']}

        [클러스터 기반 핵심 이슈 비중(Top3)]
        {cluster_context}

        [내부 보도 데이터(제목 목록, 최신순 최대 200건)]
        {title_context[:3000]}

        [외부 보충 정보 리소스]
        {ext_info}

        [엄격 가이드라인]
        1. '📌 {formatted_date} 핵심 이슈 요약': 
           - 이 섹션은 반드시 [내부 보도 통계]와 [내부 보도 데이터]만 근거로 작성하세요. (반드시 내부 데이터의 수치와 비중(%)을 활용하여 3가지를 정리하세요.)
           - 특히 [클러스터 기반 핵심 이슈 비중(Top3)]을 우선 근거로 사용하세요.
           - [외부 보충 정보 리소스]의 내용은 1번 섹션에서 절대 사용하지 마세요.
           - 3가지를 선정하되, 전체 {viz_data['total_count']}건의 기사 중 해당 이슈가 차지하는 비중이나 중요도를 언급하며 숫자를 적극 활용하세요.
           - 반드시 1., 2., 3. 번호 사용, 번호 사이 빈 줄(\\n\\n).
           - 각 항목은 본문 설명 1줄 + 다음 줄에 링크 1줄(<URL|제목 🔗>) 형태로 작성하세요.
           - 핵심 키워드는 *굵게* 표시하세요.

        2. '🌐 보도 맥락': 서울신문의 시각과 외부 여론/데이터 비교 분석.
        3. '📚 보충 리소스': 제공된 리소스를 활용해 큐레이션.
        4. '🤖 교차 분석': 우리 보도와 외부 관심사의 접점을 요약.
        5. '🔮 최종 AI 인사이트': 이슈를 종합하여 파급력과 제언을 한 문장으로 작성.
        """

        try:
            res = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            report_body = res.choices[0].message.content
        except Exception:
            fallback_lines = []
            if issue_breakdown:
                for i, row in enumerate(issue_breakdown, start=1):
                    fallback_lines.append(
                        f"{i}. 전체 {total_count}건 중 **{row['example_title']}** 이슈가 {row['count']}건({row['ratio_pct']}%) 비중입니다.\n"
                        f"<{row['example_url']}|{row['example_title']} 🔗>"
                    )
            else:
                fallback_lines.append("1. 다중 기사 클러스터가 충분하지 않아 핵심 이슈 비중 산출이 제한됩니다.")
            fallback_lines.append("\n2. 🌐 보도 맥락: 외부 보충 정보 연결은 네트워크 상태가 불안정해 생략되었습니다.")
            fallback_lines.append("3. 📚 보충 리소스: 연결 복구 후 재시도 시 최신 링크를 제공합니다.")
            fallback_lines.append("4. 🤖 교차 분석: 내부 데이터 기준으로는 단발성 기사 비중이 높습니다.")
            fallback_lines.append("5. 🔮 최종 AI 인사이트: 반복적으로 묶이는 이슈가 늘어날수록 분석 신뢰도가 높아집니다.")
            report_body = "\n\n".join(fallback_lines)

        # 하단 다른 카테고리 링크 조립
        other_links = [f"• <{url}|{cat} 🔗>" for cat, url in self.category_links.items() if cat != target_category]
        footer = "\n\n---\n**🔽 다른 카테고리 소식 더 보러가기**\n" + "  ".join(other_links)
        
        # 최종 리포트 텍스트 조립
        full_report = f"{header}\n{report_body}{footer}"

        # 텍스트와 통계 데이터를 동시에 반환 (Streamlit 호환)
        return {
            "report": full_report,
            "viz_data": viz_data
        }