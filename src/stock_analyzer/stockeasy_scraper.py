"""
StockEasy 데이터 수집 모듈

API 호출 또는 Selenium 크롤링을 통해 종목 데이터를 수집합니다.
"""

import time
import json
import logging
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
from pathlib import Path

import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from . import config

# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StockEasyScraper:
    """StockEasy 웹 사이트에서 데이터를 수집하는 스크래퍼"""
    
    def __init__(self, token: Optional[str] = None):
        logger.info(f"StackEasyScraper initialized: {id(self)}")
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            
        self.driver = None
        self.cookie_file = Path(__file__).parent.parent.parent / "stockeasy_cookies.json"
        
    def __del__(self):
        """소멸자: 브라우저 종료"""
        # logger.info(f"StackEasyScraper __del__ called: {id(self)}")
        if hasattr(self, 'quit'):
            self.quit()
            
    def _save_cookies(self):
        """현재 브라우저의 쿠키를 파일에 저장"""
        if not self.driver:
            return
        import json
        with open(self.cookie_file, 'w', encoding='utf-8') as f:
            json.dump(self.driver.get_cookies(), f, ensure_ascii=False, indent=2)
        logger.info(f"쿠키 저장 완료: {self.cookie_file}")

    def quit(self):
        """브라우저 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"브라우저 종료 중 오류: {e}")
            finally:
                self.driver = None
            logger.info(f"Selenium 브라우저가 정상적으로 종료되었습니다. ({id(self)})")
    
    def _load_cookies(self) -> bool:
        """파일에서 쿠키를 로드하여 브라우저에 적용"""
        import json
        import os
        
        if not os.path.exists(self.cookie_file):
            return False
        
        try:
            with open(self.cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    logger.warning(f"쿠키 추가 실패: {e}")
            
            logger.info(f"✅ 쿠키 로드 완료: {self.cookie_file}")
            return True
        except Exception as e:
            logger.error(f"쿠키 로드 실패: {e}")
            return False
    
    def _check_login_alert(self) -> bool:
        """로그인 Alert이 있는지 확인하고 처리"""
        try:
            from selenium.common.exceptions import NoAlertPresentException
            alert = self.driver.switch_to.alert
            alert_text = alert.text
            if "로그인" in alert_text:
                logger.warning(f"⚠️ 로그인 필요: {alert_text}")
                alert.accept()
                return True
        except NoAlertPresentException:
            pass
        except Exception as e:
            logger.debug(f"Alert 확인 중 예외: {e}")
        return False
    
    def _init_selenium(self):
        """Selenium 드라이버 초기화"""
        if self.driver:
            # 드라이버 상태 확인 (Health Check)
            try:
                # 가벼운 속성 접근으로 세션 유효성 확인
                _ = self.driver.current_window_handle
                return  # 정상, 재사용
            except Exception as e:
                logger.warning(f"기존 드라이버 세션이 유효하지 않음 (재시작): {e}")
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None

        
        import os
        
        options = webdriver.ChromeOptions()
        
        # 자동화 감지 우회 설정 (login_helper.py와 동일하게 유지)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # 쿠키 파일이 있으면 headless 모드 사용 (디버깅을 위해 잠시 해제)
        # if os.path.exists(self.cookie_file):
        #     if config.SELENIUM_HEADLESS:
        #         options.add_argument('--headless')
        #     logger.info("저장된 쿠키 발견 - 자동 로그인 시도")
        # else:
        #     logger.warning("⚠️ 쿠키 파일이 없습니다. login_helper.py를 먼저 실행하세요")
        #     if config.SELENIUM_HEADLESS:
        #         options.add_argument('--headless')
        
        # [수정] 로그인 문제 해결을 위해 무조건 화면 표시 (Headless 끔)
        logger.info("로그인 유지를 위해 브라우저 화면을 표시합니다.")
        
        options.add_argument(f'--window-size={config.SELENIUM_WINDOW_SIZE[0]},{config.SELENIUM_WINDOW_SIZE[1]}')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        
        self.driver = webdriver.Chrome(options=options)
        logger.info("Selenium 드라이버 초기화 완료")
        
        # 쿠키 로드 시도
        if os.path.exists(self.cookie_file):
            # StockEasy 도메인에 먼저 접속해야 쿠키를 추가할 수 있음
            self.driver.get("https://stockeasy.intellio.kr")
            time.sleep(1)
            
            # 로그인 alert 먼저 닫기 (쿠키 추가를 방해하므로)
            try:
                from selenium.common.exceptions import NoAlertPresentException
                alert = self.driver.switch_to.alert
                logger.info(f"Alert 감지 및 닫기: {alert.text}")
                alert.accept()
                time.sleep(0.5)
            except NoAlertPresentException:
                pass
            except Exception as e:
                logger.debug(f"Alert 확인 중 예외: {e}")
            
            # 이제 쿠키 추가
            self._load_cookies()
            self.driver.refresh()
            time.sleep(1.5)
            
            # Refresh 후에도 alert가 뜰 수 있으므로 한 번 더 확인
            try:
                from selenium.common.exceptions import NoAlertPresentException
                alert = self.driver.switch_to.alert
                logger.info(f"Refresh 후 Alert 감지 및 닫기: {alert.text}")
                alert.accept()
                time.sleep(0.5)
            except NoAlertPresentException:
                logger.info("✅ Alert 없음 - 로그인 성공으로 추정")
            except Exception as e:
                logger.debug(f"Refresh 후 Alert 확인 중 예외: {e}")
        
    # [Removed redundant collect_stock_data methods that moved to StockDataCollector]
            
    def _collect_via_selenium(self, stock_code: str) -> Optional[Dict]:
        """
        Selenium을 통해 데이터를 수집합니다.
        
        Args:
            stock_code: 종목 코드
            
        Returns:
            수집된 데이터
        """
        self._init_selenium()
        
        url = f"{config.STOCKEASY_STOCK_INFO_URL}/{stock_code}?tab=financial"
        
        try:
            self.driver.get(url)
            
            # React/Next.js 렌더링 대기
            time.sleep(1.5)
            
            # 페이지가 로드되지 않았거나 로그인이 풀린 경우 재시도 1회
            try:
                self.driver.find_element(By.CSS_SELECTOR, "h3")
            except NoSuchElementException:
                logger.warning(f"[{stock_code}] 페이지 로드 지연 또는 로그인 이슈 발생 - 1초 추가 대기")
                time.sleep(1.5)
            
            # 로그인 Alert 확인
            if self._check_login_alert():
                logger.error(f"[{stock_code}] 로그인이 필요합니다")
                logger.error("해결 방법: python -m stock_analyzer.login_helper 실행 후 로그인하세요")
                return None
            
            # 재무 건전성 데이터 추출
            financial_health = self._extract_financial_health()
            
            # 투자지표 데이터 추출
            indicators = self._extract_indicators()
            
            # RS값 추출 (소개 탭으로 이동 필요할 수 있음)
            rs_value = self._extract_rs_value(stock_code)
            
            # 종목명 추출
            stock_name = self._extract_stock_name()
            
            # 데이터 유효성 검사 (로그인 실패 등으로 데이터가 없는 경우 방지)
            if stock_name == "Unknown" and financial_health.get("score") == 0:
                logger.warning(f"[{stock_code}] 데이터 추출 실패 (유효하지 않은 데이터)")
                return None
            
            return {
                "code": stock_code,
                "name": stock_name,
                "financial_health": financial_health,
                "indicators": indicators,
                "rs_value": rs_value
            }
            
        except Exception as e:
            logger.error(f"Selenium 크롤링 실패: {e}")
            # [Fix] 특정 종목 크롤링 실패 시 드라이버를 완전히 새로고침하기보다 
            # 세션 유지 여부만 확인하고 계속 진행하도록 함
            return None
            
    def quit(self):
        """StockEasyScraper 종료용 편의 메서드"""
        if self.scraper and hasattr(self.scraper, 'quit'):
            self.scraper.quit()
    
    # 호환성을 위해 별칭 추가
    scrape_stock = _collect_via_selenium
            
    def _extract_financial_health(self) -> Dict:
        """재무 건전성 데이터 추출 (StockEasy 실제 HTML 구조 기반)"""
        try:
            # '재무 건전성' 섹션 찾기
            section = self.driver.find_element(By.XPATH, "//h3[contains(text(), '재무 건전성')]/ancestor::div[contains(@class, 'rounded-lg')]")
            
            # 점수: text-2xl bold 클래스의 숫자
            score_el = section.find_element(By.CSS_SELECTOR, "span.text-2xl")
            score_text = score_el.text.strip()
            score = int(score_text) if score_text else None
            
            # 등급: '등급'을 포함하는 텍스트 찾기 (예: "C등급", "B등급")
            grade = None
            try:
                # 방법 1: '등급' 포함 텍스트 찾기
                grade_el = section.find_element(By.XPATH, ".//*[contains(text(), '등급')]")
                grade_text = grade_el.text.strip()  # 예: "C등급"
                # 정규식으로 등급 문자만 추출 (A+, A, B, C, D, F)
                import re
                match = re.search(r'([A-F][+]?)', grade_text)
                if match:
                    grade = match.group(1)
            except:
                # 방법 2: font-bold인 span 중에서 짧은 텍스트 찾기
                try:
                    grade_candidates = section.find_elements(By.CSS_SELECTOR, "span.font-bold")
                    for candidate in grade_candidates:
                        text = candidate.text.strip()
                        if '등급' in text and len(text) <= 5:
                            import re
                            match = re.search(r'([A-F][+]?)', text)
                            if match:
                                grade = match.group(1)
                                break
                except:
                    pass
            
            return {
                "score": score,
                "grade": grade,
                "percentile": None
            }
        except Exception as e:
            logger.warning(f"재무 건전성 추출 실패: {e}")
            return {"score": None, "grade": None, "percentile": None}
            
            
            
    def _extract_indicators(self) -> Dict:
        """투자지표 추출 (StockEasy 실제 HTML 구조 기반)"""
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            # '투자 지표' 섹션 찾기 (여러 변형 시도)
            section = None
            for text_variation in ['투자 지표', '투자지표']:
                try:
                    section = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, f"//h3[contains(text(), '{text_variation}')]/ancestor::div[contains(@class, 'rounded-lg')]"))
                    )
                    break
                except:
                    continue
            
            if not section:
                logger.warning("투자지표 섹션을 찾을 수 없습니다")
                return {"growth": None, "profitability": None, "stability": None, "valuation": None}
            
            indicators = {}
            indicator_map = {
                "성장성": "growth",
                "수익성": "profitability",
                "안정성": "stability",
                "밸류에이션": "valuation"
            }
            
            for kr_name, en_name in indicator_map.items():
                try:
                    # 한글 이름으로 해당 지표의 span 찾기
                    indicator_span = section.find_element(By.XPATH, f".//span[contains(text(), '{kr_name}')]")
                    
                    # 해당 span의 부모 div 찾기
                    parent_div = indicator_span.find_element(By.XPATH, "./ancestor::div[contains(@class, 'border')][1]")
                    
                    # 모든 span 요소에서 등급 찾기
                    all_spans = parent_div.find_elements(By.TAG_NAME, "span")
                    
                    grade = None
                    for span in all_spans:
                        text = span.text.strip()
                        # A+, A, B, C, D, F 같은 짧은 등급 텍스트만 선택 (지표명 제외)
                        if text and len(text) <= 2 and any(c in text for c in ['A', 'B', 'C', 'D', 'F']) and text != kr_name:
                            grade = text
                            break
                    
                    indicators[en_name] = grade
                except Exception as e:
                    logger.debug(f"{kr_name} 추출 실패: {e}")
                    indicators[en_name] = None
                    
            return indicators
        except Exception as e:
            logger.warning(f"투자지표 추출 실패: {e}")
            return {"growth": None, "profitability": None, "stability": None, "valuation": None}
        
    def _extract_rs_value(self, stock_code: str) -> Optional[float]:
        """RS값 추출 (사용 안 함 - 항상 None 반환)"""
        # RS 값은 사용하지 않기로 결정
        return None


    def _extract_stock_name(self) -> str:
        """종목명 추출"""
        try:
            name_element = self.driver.find_element(By.CSS_SELECTOR, "h1, [class*='stock-name'], [class*='종목명']")
            return name_element.text.strip()
        except:
            return "Unknown"
            
    def _extract_grade_from_text(self, text: str) -> Optional[str]:
        """텍스트에서 등급 추출"""
        import re
        match = re.search(r'\b([A-F])\b', text)
        if match:
            return match.group(1)
        return None
        
    def _parse_api_response(self, stock_code: str, api_data: Dict) -> Dict:
        """API 응답을 파싱합니다"""
        # TODO: 실제 API 응답 구조에 맞게 구현
        # 현재는 플레이스홀더
        return {
            "code": stock_code,
            "name": api_data.get("name", "Unknown"),
            "financial_health": {
                "score": api_data.get("financial_score"),
                "grade": api_data.get("financial_grade"),
                "percentile": api_data.get("financial_percentile")
            },
            "indicators": {
                "growth": api_data.get("growth_grade"),
                "profitability": api_data.get("profitability_grade"),
                "stability": api_data.get("stability_grade"),
                "valuation": api_data.get("valuation_grade")
            },
            "rs_value": api_data.get("rs_value")
        }
        
class StockDataCollector:
    """StockEasy에서 종목 데이터를 수집하는 클래스"""
    
    def __init__(self, method: str = "selenium", token: Optional[str] = None):
        self.method = method
        self.token = token
        self.scraper = None
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        if self.method == "selenium":
            try:
                self.scraper = StockEasyScraper()
            except Exception as e:
                logger.error(f"Selenium 스크래퍼 초기화 실패: {e}")
                
    def __del__(self):
        """소멸자: 브라우저 종료"""
        if self.scraper and hasattr(self.scraper, 'driver'):
            try:
                # getattr를 사용하여 quit 메서드 안전하게 호출
                if hasattr(self.scraper, 'quit'):
                    self.scraper.quit()
                elif hasattr(self.scraper.driver, 'quit'):
                    self.scraper.driver.quit()
            except:
                pass

    def collect_stock_data(self, stock_code: str, use_cache: bool = True) -> Optional[Dict]:
        """
        종목 데이터를 수집합니다.
        """
        if use_cache:
            data = self._load_from_cache(stock_code)
            if data:
                return data
        
        if self.method == "api":
            return self._collect_via_api(stock_code)
        else:
            if not self.scraper:
                try:
                    self.scraper = StockEasyScraper()
                except Exception as e:
                    logger.error(f"Selenium 스크래퍼 초기화 실패: {e}")
                    return None
            
            # Selenium 수집 시도
            result = self.scraper.scrape_stock(stock_code)
            
            # 수집 성공 시 캐시 저장
            if result:
                self._save_to_cache(stock_code, result)
            return result

    def _collect_via_api(self, stock_code: str) -> Optional[Dict]:
        """API를 통해 데이터를 수집합니다."""
        url = f"{config.STOCKEASY_BASE_URL}{config.API_ENDPOINTS['financial'].format(code=stock_code)}"
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json() # Simple return for now, reuse parsing logic if accessible
        except Exception as e:
            logger.error(f"API 호출 실패: {e}")
            return None
        
    def _load_from_cache(self, stock_code: str) -> Optional[Dict]:
        """캐시에서 데이터 로드"""
        cache_path = config.get_cache_path(stock_code)
        
        if not cache_path.exists():
            return None
            
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # collected_at 필드가 없으면 캐시를 무효로 간주 (경고 없이)
            if "collected_at" not in data:
                return None
                
            # 캐시 만료 확인
            collected_at = datetime.fromisoformat(data["collected_at"])
            if datetime.now() - collected_at > timedelta(hours=config.CACHE_EXPIRY_HOURS):
                logger.info(f"[{stock_code}] 캐시 만료")
                return None
                
            return data
            
        except Exception as e:
            # 캐시 로드 실패 시 조용히 무시 (디버그 레벨로 변경)
            logger.debug(f"캐시 로드 실패: {e}")
            return None
            
    def _save_to_cache(self, stock_code: str, data: Dict):
        """데이터를 캐시에 저장"""
        cache_path = config.get_cache_path(stock_code)
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"[{stock_code}] 캐시 저장 완료")
        except Exception as e:
            logger.warning(f"캐시 저장 실패: {e}")
            
    def collect_batch(self, stock_codes: List[str], use_cache: bool = True) -> Dict[str, Dict]:
        """
        여러 종목의 데이터를 배치로 수집합니다.
        
        Args:
            stock_codes: 종목 코드 리스트
            use_cache: 캐시 사용 여부
            
        Returns:
            종목 코드를 키로 하는 데이터 딕셔너리
        """
        results = {}
        
        for i, code in enumerate(stock_codes, 1):
            logger.info(f"진행: {i}/{len(stock_codes)} - {code}")
            
            data = self.collect_stock_data(code, use_cache)
            if data:
                results[code] = data
                
            # Rate limiting
            if i < len(stock_codes):
                time.sleep(config.RATE_LIMIT_DELAY)
                
        logger.info(f"배치 수집 완료: {len(results)}/{len(stock_codes)} 성공")
        return results


# 편의 함수
def collect_stocks(stock_codes: List[str], method: str = "selenium", 
                  token: Optional[str] = None, use_cache: bool = True) -> Dict[str, Dict]:
    """
    종목 데이터를 수집하는 편의 함수
    
    Args:
        stock_codes: 종목 코드 리스트
        method: 'api' 또는 'selenium'
        token: API 토큰 (API 방식 사용 시)
        use_cache: 캐시 사용 여부
        
    Returns:
        수집된 데이터
    """
    collector = StockDataCollector(method=method, token=token)
    return collector.collect_batch(stock_codes, use_cache=use_cache)


def get_top_stocks_from_208week(market: str = "KOSPI", n_stocks: int = 200) -> Optional[pd.DataFrame]:
    """
    208Week 프로젝트의 시가총액 상위 종목 리스트 가져오기
    
    Args:
        market: 'KOSPI' 또는 'KOSDAQ'
        n_stocks: 가져올 종목 수
    
    Returns:
        DataFrame with columns: Code, Name, 현재가
    """
    try:
        import sys
        import os
        
        # 208Week의 loader 모듈 import
        try:
            from src.data.loader import get_stock_list_naver
        except ImportError:
            # Standalone 실행 시 등을 대비해 상위 경로 추가 시도
            sys.path.append(str(Path(__file__).parent.parent.parent))
            from src.data.loader import get_stock_list_naver
        
        # 종목 리스트 가져오기
        stock_df = get_stock_list_naver(market, n_stocks)
        
        logger.info(f"208Week에서 {market} 상위 {len(stock_df)}개 종목 가져옴")
        return stock_df
        
    except Exception as e:
        logger.error(f"208Week 종목 리스트 가져오기 실패: {e}")
        logger.info("Fallback: 네이버 금융 직접 크롤링 시도")
        
        # Fallback: 직접 크롤링 (208Week 코드와 동일)
        try:
            import requests
            from bs4 import BeautifulSoup
            
            sosok = 0 if market == "KOSPI" else 1
            stocks = []
            
            pages = (n_stocks // 50) + 2
            for page in range(1, pages):
                url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
                res.encoding = 'cp949'
                
                soup = BeautifulSoup(res.text, 'lxml')
                table = soup.find('table', {'class': 'type_2'})
                
                if not table:
                    continue
                
                for tr in table.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) <= 1:
                        continue
                    
                    try:
                        rank = tds[0].text.strip()
                        if not rank.isdigit():
                            continue
                    except:
                        continue
                    
                    try:
                        a_tag = tds[1].find('a')
                        if not a_tag:
                            continue
                        
                        name = a_tag.text.strip()
                        href = a_tag['href']
                        code = href.split('=')[-1].zfill(6)
                        
                        # [Common Stock Filter] 보통주(0)가 아니면 제외
                        if not code.endswith('0'):
                            continue
                        
                        # ETF 및 기타 지수 종목 필터링 강화
                        etf_keywords = [
                            'KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'RISE', 'ARIRANG',
                            'HANARO', 'KINDEX', 'KOSEC', 'KOSEF', 'TREX', 'SMART', 'FOCUS', 'WOORI',
                            'KIWOOM', 'PLUS', 'N2', 'KOSPI', 'KOSDAQ', '레버리지', '인버스', '선물', ' 200', ' 150'
                        ]
                        if any(kw in name.upper() for kw in etf_keywords) or name.endswith('TR'):
                            continue
                        
                        try:
                            price_txt = tds[2].text.strip().replace(',', '')
                            current_price = int(price_txt)
                        except:
                            current_price = 0
                        
                        stocks.append({'Code': code, 'Name': name, '현재가': current_price})
                    except:
                        continue
                
                if len(stocks) >= n_stocks:
                    break
            
            return pd.DataFrame(stocks).head(n_stocks)
            
        except Exception as fallback_error:
            logger.error(f"Fallback 크롤링도 실패: {fallback_error}")
            return None

