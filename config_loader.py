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
    
    def get_bybit_api_key(self, coin: str) -> Dict[str, str]:
        """
        특정 코인의 Bybit API 키 조회
        
        Args:
            coin: 코인 심볼 (BTC, ETH, SOL 등)
            
        Returns:
            API 키 및 시크릿
        """
        api_keys = self.load_config("api_keys.json")
        
        # 코인 심볼에서 USDT 부분 제거 (예: BTCUSDT -> BTC)
        coin_base = coin.replace("USDT", "")
        
        # 해당 코인의 API 키 조회
        coin_api = api_keys.get("bybit_api", {}).get(coin_base, {})
        
        # API 키가 없으면 빈 딕셔너리 반환
        if not coin_api:
            print(f"경고: {coin_base}에 대한 API 키가 설정되지 않았습니다.")
            return {"key": "", "secret": ""}
        
        return coin_api
    
    def get_claude_api_key(self) -> Dict[str, str]:
        """
        Claude API 키 조회
        
        Returns:
            API 키 및 모델 정보
        """
        api_keys = self.load_config("api_keys.json")
        claude_api = api_keys.get("claude_api", {})
        
        # API 키가 없으면 빈 딕셔너리 반환
        if not claude_api:
            print("경고: Claude API 키가 설정되지 않았습니다.")
            return {"key": "", "model": ""}
        
        return claude_api
    
    def get_execution_server_config(self) -> Dict[str, str]:
        """
        실행 서버 설정 조회
        
        Returns:
            실행 서버 URL 및 API 키
        """
        api_keys = self.load_config("api_keys.json")
        execution_server = api_keys.get("execution_server", {})
        
        # 설정이 없으면 기본값 반환
        if not execution_server:
            print("경고: 실행 서버 설정이 없습니다.")
            return {"url": "http://localhost:8001/execute", "api_key": ""}
        
        return execution_server
    
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
                "BTC": {
                    "key": "your-btc-api-key",
                    "secret": "your-btc-api-secret"
                },
                "ETH": {
                    "key": "your-eth-api-key",
                    "secret": "your-eth-api-secret"
                },
                "SOL": {
                    "key": "your-sol-api-key",
                    "secret": "your-sol-api-secret"
                }
            },
            "claude_api": {
                "key": "your-claude-api-key",
                "model": "claude-3-7-sonnet-20250219"
            },
            "execution_server": {
                "url": "http://execution-server-address:port/execute",
                "api_key": "execution-server-api-key"
            }
        }
        self.save_config("api_keys.json", api_keys)
        
        # 시스템 설정 파일
        system_settings = {
            "webhook_port": 8000,
            "log_level": "INFO",
            "test_mode": False,
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "candles_count": 100,            # 수집할 캔들 수 설정
            "retry_attempts": 3,
            "retry_delay_seconds": 30
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
    for coin in ["BTC", "ETH", "SOL"]:
        api_key = config.get_bybit_api_key(f"{coin}USDT")
        print(f"{coin} API 키: {api_key.get('key', '없음')}")