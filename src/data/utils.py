from datetime import datetime
import json
import os
import streamlit as st

# Force reload marker: v1.0.1
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS_FILE = os.path.join(BASE_DIR, "config", "user_settings.json")
HISTORY_FILE = os.path.join(BASE_DIR, "config", "backtest_history.json")

def load_settings():
    """이전 설정값 불러오기"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # 기본값
    return {
        'market': 'KOSPI',
        'lookback': 208,
        'n_stocks': 200,
        'bc_breakout_days': 60,
        'max_holding_months': 0,
        'defense_trailing_pct': 0.0,
        'profit_trailing_pct': 0.0,
        'bc_exit_days': 0,
        'exit_target': 'D/E Boundary',
        'exit_method': '목표 도달 후 20일선 이탈',
        'stop_loss_pct': 0.0,
        'bt_start_date': '2023-01-02',
        'bt_end_date': datetime.now().strftime('%Y-%m-%d'),
        'cooldown_days': 0,
        'inv_per_stock': 1000
    }

def save_settings(settings):
    """현재 설정값 저장"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Settings save error: {e}")

class NumpyEncoder(json.JSONEncoder):
    """Numpy 타입 시리얼라이즈를 위한 엔코더"""
    def default(self, obj):
        if isinstance(obj, (int, float, str, bool, type(None))):
            return super().default(obj)
        if hasattr(obj, 'tolist'): # numpy arrays
            return obj.tolist()
        if hasattr(obj, 'item'): # numpy scalars
            try:
                return obj.item()
            except:
                pass
        return str(obj)

def load_history():
    """백테스트 히스토리 불러오기"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except Exception as e:
            print(f"History load error: {e}")
            # 만약 파일이 손상되었다면 빈 리스트 반환 (또는 백업 처리)
    return []

def save_history(history):
    """백테스트 히스토리 저장"""
    try:
        # Create config directory if not exists
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    except Exception as e:
        print(f"History save error: {e}")
