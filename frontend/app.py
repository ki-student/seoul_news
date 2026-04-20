import streamlit as st
import requests
import altair as alt
import os
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

# 백엔드 로직 직접 임포트
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "backend"))

from backend.analyzer import NewsAnalyzer

# 환경 변수 로드
load_dotenv()

# Qdrant 및 분석 엔진 초기화
qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_ENDPOINT"),
    api_key=os.getenv("QDRANT_API_KEY"),
    timeout=60
)
analyzer = NewsAnalyzer()
USER_COLLECTION = "user_profiles"
CATEGORY_OPTIONS = ["전체", "정치", "경제", "사회", "국제", "문화", "스포츠", "정책.자치", "연애"]

st.set_page_config(page_title="서울신문 AI 이슈 브리핑", layout="wide")

def get_user_id(username):
    return hashlib.md5(username.encode()).hexdigest()

# --- [세션 상태 관리] ---
if "user_info" not in st.session_state:
    st.session_state.user_info = None
if "analyze_requested" not in st.session_state:
    st.session_state.analyze_requested = False
if "profile_saved_message" not in st.session_state:
    st.session_state.profile_saved_message = ""

def logout():
    st.session_state.user_info = None
    if "current_cat" in st.session_state:
        del st.session_state.current_cat
    st.session_state.analyze_requested = False
    st.rerun()

# --- [메인 UI 로직] ---
if st.session_state.user_info is None:
    st.title("🗞️ 서울신문 AI 서비스")
    st.caption("실시간 뉴스 분석 및 자동 슬랙 브리핑 시스템")
    
    tab1, tab2 = st.tabs(["로그인", "회원가입"])
    
    with tab1:
        login_id = st.text_input("사용자 이름(ID)", placeholder="성함을 입력하세요")
        if st.button("로그인"):
            try:
                point_id = get_user_id(login_id)
                result = qdrant_client.retrieve(collection_name=USER_COLLECTION, ids=[point_id])
                if result:
                    st.session_state.user_info = result[0].payload
                    st.success(f"{login_id}님, 환영합니다!")
                    st.rerun()
                else:
                    st.error("사용자를 찾을 수 없습니다. 회원가입을 먼저 진행해주세요.")
            except Exception as e:
                st.error(f"로그인 중 오류 발생: {e}")

    with tab2:
        st.subheader("새로운 사용자로 등록")
        
        # 슬랙 가이드 추가
        with st.expander("💡 슬랙 웹훅(Webhook) URL 발급 방법 (처음이신 분 클릭!)"):
            st.markdown("""
            **1단계: 슬랙 앱(App) 생성**
            - [Slack API 대시보드](https://api.slack.com/apps)에 접속합니다.
            - **Create New App** -> **From scratch**를 선택합니다.
            - 앱 이름(예: `SeoulNews`)을 입력하고 워크스페이스를 선택한 후 **Create App**을 누릅니다.

            **2단계: Incoming Webhooks 활성화**
            - 왼쪽 메뉴에서 **Incoming Webhooks**를 클릭합니다.
            - Activate Incoming Webhooks 스위치를 **On**으로 바꿉니다.

            **3단계: 웹훅 URL 발급 및 채널 지정**
            - 하단의 **Add New Webhook to Workspace** 버튼을 클릭합니다.
            - 리포트를 받을 **슬랙 채널**을 선택한 후 **Allow (허용)**를 누릅니다.
            - 생성된 `https://hooks.slack.com/services/...` 주소를 아래 입력창에 붙여넣으세요!
            """)

        new_name = st.text_input("성함", placeholder="ID로 사용됩니다")
        new_slack = st.text_input("슬랙 Webhook URL", placeholder="https://hooks.slack.com/services/...")
        new_interests = st.multiselect("관심 카테고리 설정", CATEGORY_OPTIONS)
        
        if st.button("가입 및 시작하기"):
            if not new_name or not new_slack or not new_interests:
                st.warning("모든 정보를 입력해주세요.")
            else:
                user_data = {
                    "username": new_name,
                    "slack_webhook": new_slack,
                    "interests": ",".join(new_interests)
                }
                try:
                    point_id = get_user_id(new_name)
                    # 이미 가입된 유저인지 확인
                    existing = qdrant_client.retrieve(collection_name=USER_COLLECTION, ids=[point_id])
                    if existing:
                        st.warning("이미 가입된 성함입니다. 로그인을 이용하시거나 다른 성함으로 가입해주세요.")
                    else:
                        qdrant_client.upsert(
                            collection_name=USER_COLLECTION,
                            points=[models.PointStruct(
                                id=point_id,
                                vector=[0.0] * 128,
                                payload=user_data
                            )]
                        )
                        st.session_state.user_info = user_data
                        st.success("회원가입 성공!")
                        st.rerun()
                except Exception as e:
                    st.error(f"회원가입 오류: {e}")

else:
    user = st.session_state.user_info
    current_interests = [item for item in user.get("interests", "").split(",") if item]
    
    if st.session_state.profile_saved_message:
        st.success(st.session_state.profile_saved_message)
        st.session_state.profile_saved_message = ""

    with st.sidebar:
        st.header(f"👤 {user['username']} 님")
        st.write(f"**현재 관심사:** \n {user['interests']}")
        with st.expander("회원정보 수정"):
            edit_slack = st.text_input("슬랙 Webhook URL 수정", value=user.get("slack_webhook", ""), key="edit_slack_webhook")
            edit_interests = st.multiselect("관심 카테고리 수정", CATEGORY_OPTIONS, default=[x for x in current_interests if x in CATEGORY_OPTIONS], key="edit_interests")
            if st.button("정보 저장", use_container_width=True):
                if not edit_slack or not edit_interests:
                    st.warning("정보를 모두 입력해주세요.")
                else:
                    updated_user = {
                        "username": user["username"],
                        "slack_webhook": edit_slack,
                        "interests": ",".join(edit_interests)
                    }
                    try:
                        point_id = get_user_id(user["username"])
                        qdrant_client.upsert(
                            collection_name=USER_COLLECTION,
                            points=[models.PointStruct(id=point_id, vector=[0.0] * 128, payload=updated_user)]
                        )
                        st.session_state.user_info = updated_user
                        st.session_state.profile_saved_message = "정보가 수정되었습니다."
                        st.rerun()
                    except Exception as e:
                        st.error(f"정보 수정 오류: {e}")
        st.divider()
        if st.button("로그아웃"):
            logout()

    st.title(f"🚀 {user['username']}님을 위한 실시간 브리핑")
    interests_list = user['interests'].split(",")
    if "전체" in interests_list:
        interests_list.remove("전체")
        interests_list.insert(0, "전체")
    
    st.subheader("🎯 분석할 카테고리를 선택하세요")
    cols = st.columns(3)
    for idx, cat in enumerate(interests_list):
        label = f"🌟 {cat} 브리핑" if cat == "전체" else f"🔍 {cat} 분석"
        if cols[idx % 3].button(label, key=f"btn_{cat}", use_container_width=True):
            st.session_state.current_cat = cat
            st.session_state.analyze_requested = True

    if "current_cat" in st.session_state and st.session_state.get("analyze_requested"):
        cat = st.session_state.current_cat
        with st.spinner(f"'{cat}' 분야 분석 중..."):
            try:
                # 백엔드 API 호출 대신 직접 함수 호출
                result = analyzer.analyze_category(cat)
                
                # 슬랙 전송
                if user['slack_webhook'].startswith("https://hooks.slack.com"):
                    requests.post(user['slack_webhook'], json={"text": result['report']})
                    st.success(f"✅ {cat} 분석 완료 및 슬랙 전송 성공!")
                
                viz_data = result.get("viz_data", {})
                issue_breakdown = viz_data.get("issue_breakdown", [])
                
                st.divider()
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.metric("분석 기사 수", f"{viz_data.get('total_count', 0)}건")
                    if issue_breakdown:
                        for issue in issue_breakdown:
                            st.write(f"- {issue['label']} ({issue['count']}건, {issue['ratio_pct']}%)")
                with col2:
                    if issue_breakdown:
                        chart_rows = [{"기사": issue["label"], "기사 수": issue["count"]} for issue in issue_breakdown]
                        chart = (alt.Chart(alt.Data(values=chart_rows)).mark_bar().encode(x=alt.X("기사 수:Q"), y=alt.Y("기사:N", sort="-x")))
                        st.altair_chart(chart, use_container_width=True)
                
                st.markdown(f"### 📝 {cat} AI 분석 리포트")
                st.info(result.get("report", "리포트가 없습니다."))
            except Exception as e:
                st.error(f"분석 중 오류 발생: {e}")
        st.session_state.analyze_requested = False
