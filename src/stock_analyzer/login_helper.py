"""
StockEasy 로그인 헬퍼 스크립트

사용법:
    python -m stock_analyzer.login_helper
    
또는:
    cd stock_analyzer
    python login_helper.py
"""

from selenium import webdriver
import time
import json
import logging
from pathlib import Path

# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=" * 60)
    print("StockEasy 로그인 헬퍼")
    print("=" * 60)
    print()
    print("📋 이 도구는 StockEasy 로그인 정보를 저장합니다")
    print()
    print("절차:")
    print("1. Chrome 브라우저가 열립니다")
    print("2. StockEasy에 로그인하세요")
    print("3. 로그인 후 이 터미널로 돌아와서 Enter를 누르세요")
    print()
    
    # Chrome 드라이버 초기화
    print("🌐 Chrome 브라우저를 시작하는 중...")
    options = webdriver.ChromeOptions()
    
    # 자동화 감지 우회 설정
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-blink-features=AutomationControlled')
    
    # 일반 모드로 실행
    options.add_argument('--start-maximized')
    
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"❌ 오류: Chrome 드라이버 초기화 실패")
        print(f"   {e}")
        print()
        print("해결 방법:")
        print("1. Chrome 브라우저가 설치되어 있는지 확인")
        print("2. selenium 패키지가 설치되어 있는지 확인: pip install selenium")
        return
    
    # StockEasy 로그인 페이지로 이동
    print("✅ 브라우저가 열렸습니다")
    print("📍 StockEasy로 이동 중...")
    driver.get("https://stockeasy.intellio.kr")
    time.sleep(2)
    
    print()
    print("=" * 60)
    print("👉 브라우저에서 StockEasy에 로그인하세요")
    print("=" * 60)
    print()
    print("로그인 완료 후 이 터미널로 돌아와서 Enter를 누르세요...")
    
    input()
    
    # 쿠키 저장
    print()
    print("💾 로그인 정보를 저장하는 중...")
    cookies = driver.get_cookies()
    
    # 프로젝트 루트 디렉토리에 저장
    cookie_file = Path(__file__).parent.parent.parent / "stockeasy_cookies.json"
    
    with open(cookie_file, "w", encoding='utf-8') as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 로그인 정보가 저장되었습니다!")
    print(f"   파일 위치: {cookie_file}")
    print()
    print("🎉 완료! 이제 앱에서 데이터를 수집할 수 있습니다.")
    print()
    print("다음 단계:")
    print("1. streamlit run analyzer_app.py")
    print("2. 데이터 수집 시작")
    print()
    
    driver.quit()
    print("브라우저를 닫았습니다.")

if __name__ == "__main__":
    main()
