import json
import os
from typing import Dict, Any, Optional


class ConfigLoader:
    """
    설정 파일을 로드하는 유틸리티 클래스
    """
    def __init__(self, config_dir: str = "config", prompt_dir: str = "prompts"):
        """
        ConfigLoader 초기화
        
        Args:
            config_dir: 설정 파일이 저장된 디렉토리 경로
            prompt_dir: 프롬프트 템플릿이 저장된 디렉토리 경로
        """
        self.config_dir = config_dir
        self.prompt_dir = prompt_dir
        
        # 설정 디렉토리가 없으면 생성
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            
        # 프롬프트 디렉토리가 없으면 생성
        if not os.path.exists(prompt_dir):
            os.makedirs(prompt_dir)
    
    def load_config(self, filename: str) -> Dict[str, Any]:
        """
        설정 파일을 로드
        
        Args:
            filename: 설정 파일 이름
            
        Returns:
            설정 파일의 내용을 담은 딕셔너리
        """
        path = os.path.join(self.config_dir, filename)
        return self._load_json(path)
    
    def load_prompt(self, filename: str) -> Dict[str, Any]:
        """
        프롬프트 템플릿 파일을 로드
        
        Args:
            filename: 프롬프트 파일 이름
            
        Returns:
            프롬프트 파일의 내용을 담은 딕셔너리
        """
        path = os.path.join(self.prompt_dir, filename)
        return self._load_json(path)
    
    def save_config(self, filename: str, data: Dict[str, Any]) -> bool:
        """
        설정 파일 저장
        
        Args:
            filename: 설정 파일 이름
            data: 저장할 데이터
            
        Returns:
            저장 성공 여부
        """
        path = os.path.join(self.config_dir, filename)
        return self._save_json(path, data)
    
    def _load_json(self, filepath: str) -> Dict[str, Any]:
        """
        JSON 파일을 로드
        
        Args:
            filepath: JSON 파일 경로
            
        Returns:
            JSON 내용을 담은 딕셔너리
        """
        try:
            if not os.path.exists(filepath):
                return {}
                
            with open(filepath, 'r', encoding='utf-8') as file:
                return json.load(file)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            return {}
    
    def _save_json(self, filepath: str, data: Dict[str, Any]) -> bool:
        """
        JSON 파일 저장
        
        Args:
            filepath: 저장할 경로
            data: 저장할 데이터
            
        Returns:
            저장 성공 여부
        """
        try:
            with open(filepath, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving {filepath}: {e}")
            return False
    
    def create_default_configs(self) -> None:
        """
        기본 설정 파일 생성
        """
        # API 키 설정 파일
        api_keys = {
            "bybit_api": {
                "key": "your-exchange-api-key",
                "secret": "your-exchange-api-secret"
            },
            "claude_api": {
                "key": "your-claude-api-key",
                "model": "claude-3-7-sonnet-20250219"
            }
        }
        self.save_config("api_keys.json", api_keys)
        
        # 시스템 설정 파일
        system_settings = {
            "webhook_port": 8000,
            "log_level": "INFO",
            "test_mode": False,
            
            "position_size_mode": "fixed",    # "fixed" 또는 "percent"
            "position_size_fixed": 100,       # 고정 금액 (USDT)
            "position_size_percent": 10,      # 백분율 (%)
            
            "leverage": 5,                    # 고정 레버리지
            "sl_percent": 1.5,                # 손절 비율 (%)
            "tp_percent": 3.0,                # 익절 비율 (%)
            
            "retry_attempts": 3,
            "retry_delay_seconds": 30,
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "candles_count": 200              # 수집할 캔들 수 설정
        }
        self.save_config("system_settings.json", system_settings)


# 기본 사용 예시
if __name__ == "__main__":
    config = ConfigLoader()
    
    # 기본 설정 파일이 없으면 생성
    if not os.path.exists(os.path.join(config.config_dir, "api_keys.json")):
        config.create_default_configs()
        print("기본 설정 파일이 생성되었습니다. config/api_keys.json 파일에 API 키를 입력하세요.")
    
    # 설정 파일 로드
    api_keys = config.load_config("api_keys.json")
    print(f"바이비트 API 키: {api_keys.get('bybit_api', {}).get('key', '없음')}")