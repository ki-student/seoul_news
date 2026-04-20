import streamlit as st
import requests
import altair as alt

# 백엔드 서버 주소
BACKEND_URL = "http://127.0.0.1:8000"
CATEGORY_OPTIONS = ["전체", "정치", "경제", "사회", "국제", "문화", "스포츠", "정책.자치", "연애"]

st.set_page_config(page_title="서울신문 AI 이슈 브리핑", layout="wide")

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
                res = requests.post(f"{BACKEND_URL}/login", json={"username": login_id})
                if res.status_code == 200:
                    st.session_state.user_info = res.json()
                    st.success(f"{login_id}님, 환영합니다!")
                    st.rerun()
                else:
                    st.error("사용자를 찾을 수 없습니다. 회원가입을 먼저 진행해주세요.")
            except Exception as e:
                st.error(f"백엔드 서버 연결 실패: {e}")

    with tab2:
        new_name = st.text_input("성함", placeholder="ID로 사용됩니다")
        new_slack = st.text_input("슬랙 Webhook URL", placeholder="https://hooks.slack.com/services/...")
        # '전체'를 선택지에 추가했습니다.
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
                res = requests.post(f"{BACKEND_URL}/register_or_update", json=user_data)
                if res.status_code == 200:
                    st.session_state.user_info = user_data
                    st.rerun()

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
            edit_slack = st.text_input(
                "슬랙 Webhook URL 수정",
                value=user.get("slack_webhook", ""),
                key="edit_slack_webhook"
            )
            edit_interests = st.multiselect(
                "관심 카테고리 수정",
                CATEGORY_OPTIONS,
                default=[x for x in current_interests if x in CATEGORY_OPTIONS],
                key="edit_interests"
            )
            if st.button("정보 저장", use_container_width=True):
                if not edit_slack or not edit_interests:
                    st.warning("슬랙 Webhook과 관심 카테고리를 모두 입력해주세요.")
                else:
                    updated_user = {
                        "username": user["username"],
                        "slack_webhook": edit_slack,
                        "interests": ",".join(edit_interests)
                    }
                    try:
                        res = requests.post(f"{BACKEND_URL}/register_or_update", json=updated_user)
                        if res.status_code == 200:
                            st.session_state.user_info = updated_user
                            if "current_cat" in st.session_state:
                                del st.session_state.current_cat
                            st.session_state.analyze_requested = False
                            st.session_state.profile_saved_message = "회원정보 저장이 완료되었습니다."
                            st.rerun()
                        else:
                            st.error("회원정보 수정 실패: 서버 응답을 확인해주세요.")
                    except Exception as e:
                        st.error(f"회원정보 수정 중 연결 오류: {e}")
        st.divider()
        if st.button("로그아웃"):
            logout()

    st.title(f"🚀 {user['username']}님을 위한 실시간 브리핑")
    
    # 관심 카테고리 리스트화 및 정렬
    interests_list = user['interests'].split(",")
    
    # '전체'가 있다면 가장 앞으로 보냄
    if "전체" in interests_list:
        interests_list.remove("전체")
        interests_list.insert(0, "전체")
    
    st.subheader("🎯 분석할 카테고리를 선택하세요")
    
    # 버튼 배치 (3열 레이아웃)
    cols = st.columns(3)
    for idx, cat in enumerate(interests_list):
        # '전체' 카테고리는 별도 아이콘으로 강조
        label = f"🌟 {cat} 브리핑" if cat == "전체" else f"🔍 {cat} 분석"
        
        if cols[idx % 3].button(label, key=f"btn_{cat}", use_container_width=True):
            st.session_state.current_cat = cat
            st.session_state.analyze_requested = True

    # 분석 결과 표시 부분
    if "current_cat" in st.session_state and st.session_state.get("analyze_requested"):
        cat = st.session_state.current_cat
        with st.spinner(f"'{cat}' 분야의 최신 데이터를 분석 중입니다..."):
            # 백엔드 호출
            response = requests.post(f"{BACKEND_URL}/analyze?username={user['username']}&category={cat}")
            
            if response.status_code == 200:
                result = response.json()
                st.success(f"✅ {cat} 분석 완료 및 슬랙 전송 성공!")
                viz_data = result.get("viz_data", {})
                issue_breakdown = viz_data.get("issue_breakdown", [])
                
                st.divider()
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.metric("분석 기사 수", f"{viz_data.get('total_count', 0)}건")
                    st.write("**핵심 이슈 비중**")
                    st.caption("산정 기준: 2건 이상으로 묶인 클러스터만 비중에 포함됩니다.")
                    if issue_breakdown:
                        for issue in issue_breakdown:
                            st.write(f"- {issue['label']} ({issue['count']}건, {issue['ratio_pct']}%)")
                        if viz_data.get("singleton_count", 0) > 0:
                            st.caption(
                                f"나머지 {viz_data.get('singleton_count', 0)}건은 단독 기사(1건 클러스터)라 비중 표에서 제외했습니다."
                            )
                    else:
                        st.caption("2건 이상으로 묶인 이슈가 없어 비중 목록을 표시하지 않습니다.")
                with col2:
                    if issue_breakdown:
                        chart_rows = [
                            {"기사": issue["label"], "기사 수": issue["count"]}
                            for issue in issue_breakdown
                        ]
                        st.dataframe(
                            [
                                {
                                    "핵심 이슈": issue["label"],
                                    "기사 수": issue["count"],
                                    "비중(%)": issue["ratio_pct"],
                                    "대표 기사": issue["example_title"],
                                }
                                for issue in issue_breakdown
                            ],
                            use_container_width=True
                        )
                        chart = (
                            alt.Chart(alt.Data(values=chart_rows))
                            .mark_bar()
                            .encode(
                                x=alt.X("기사 수:Q", title="기사 수"),
                                y=alt.Y("기사:N", sort="-x", title="기사"),
                                tooltip=["기사:N", "기사 수:Q"],
                            )
                            .properties(height=300)
                        )
                        st.altair_chart(chart, use_container_width=True)
                    else:
                        st.info("2건 이상 클러스터가 없어 차트를 생략했습니다.")
                
                st.markdown(f"### 📝 {cat} AI 분석 리포트")
                st.info(result.get("report", "리포트가 없습니다."))
            else:
                st.error("분석 중 오류가 발생했습니다. 백엔드 서버를 확인해주세요.")
        st.session_state.analyze_requested = False