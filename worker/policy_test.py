import requests
from bs4 import BeautifulSoup
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def log(msg):
    print(f"[FINAL TEST LOG] {msg}")

def fix_encoding_test(url):
    log(f"Target URL: {url}")
    res = requests.get(url, headers=headers, timeout=10)
    
    # [핵심] UTF-8로 디코딩하되, 에러가 나는 바이트는 그냥 무시(ignore)합니다.
    # 이렇게 하면 깨진 광고 코드 등은 버리고 진짜 제목/본문만 한글로 가져옵니다.
    html_text = res.content.decode('utf-8', errors='ignore')
    
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 제목 추출
    title_tag = soup.select_one("#container > div.content > div.atic_title > h3")
    title = title_tag.get_text(strip=True) if title_tag else "태그 못 찾음"
    
    return title

if __name__ == "__main__":
    target_url = "https://go.seoul.co.kr/news/newsView.php?id=20260410019010"
    title = fix_encoding_test(target_url)
    
    print("\n" + "="*50)
    print(f"최종 한글 추출 결과: {title}")
    print("="*50 + "\n")
    
    if "창밖" in title or "창" in title: # м°Ҫ가 '창'의 깨진 모습임
        print("✅ 성공! 한글이 정상적으로 복구되었습니다.")
    else:
        print("❌ 아직 해결되지 않았습니다.")
