import json
import os
import streamlit as st

SETTINGS_FILE = "user_settings.json"

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
        'bc_breakout_days': 60
    }

def save_settings(settings):
    """현재 설정값 저장"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Settings save error: {e}")
