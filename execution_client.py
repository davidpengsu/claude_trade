import json
import logging
import time
import requests
from typing import Dict, Any, Optional

# 로깅 설정
logger = logging.getLogger("execution_client")

class ExecutionClient:
    """
    실행 서버와 통신하는 클라이언트
    
    거래 결정을 실행 서버에 전달하는 역할
    """
    
    def __init__(self, server_url: str, api_key: str):
        """
        ExecutionClient 초기화
        
        Args:
            server_url: 실행 서버 URL
            api_key: 실행 서버 API 키
        """
        self.server_url = server_url
        self.api_key = api_key
        
        # 요청 세션 생성
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "X-API-Key": api_key
        })
    
    def send_open_position(self, symbol: str, position_type: str, ai_decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        포지션 진입 신호 전송
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position_type: 포지션 타입 ("long" 또는 "short")
            ai_decision: AI 결정 정보
            
        Returns:
            서버 응답
        """
        # 진입 신호 구성
        payload = {
            "action": "open_position",
            "symbol": symbol,
            "position_type": position_type,
            "ai_decision": ai_decision,
            "timestamp": int(time.time() * 1000)
        }
        
        return self._send_request(payload)
    
    def send_close_position(self, symbol: str, position_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        포지션 청산 신호 전송
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position_info: 현재 포지션 정보 (옵션)
            
        Returns:
            서버 응답
        """
        # 청산 신호 구성
        payload = {
            "action": "close_position",
            "symbol": symbol,
            "position_info": position_info,
            "timestamp": int(time.time() * 1000)
        }
        
        return self._send_request(payload)
    
    def send_trend_touch_decision(self, symbol: str, position_info: Dict[str, Any], ai_decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        추세선 터치 결정 신호 전송
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position_info: 현재 포지션 정보
            ai_decision: AI 결정 정보
            
        Returns:
            서버 응답
        """
        # 추세선 터치 신호 구성
        payload = {
            "action": "trend_touch",
            "symbol": symbol,
            "position_info": position_info,
            "ai_decision": ai_decision,
            "timestamp": int(time.time() * 1000)
        }
        
        return self._send_request(payload)
    
    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        실행 서버에 요청 전송
        
        Args:
            payload: 요청 내용
            
        Returns:
            서버 응답
        """
        try:
            # 최대 3번 재시도
            max_retries = 3
            for retry in range(max_retries):
                try:
                    # 요청 전송
                    response = self.session.post(
                        self.server_url,
                        data=json.dumps(payload),
                        timeout=10  # 10초 타임아웃
                    )
                    
                    # 응답 확인
                    if response.status_code != 200:
                        if retry < max_retries - 1:
                            logger.warning(f"실행 서버 요청 실패 (재시도 {retry+1}/{max_retries}): {response.status_code} - {response.text}")
                            time.sleep(1)  # 재시도 전 대기
                            continue
                        return {"status": "error", "message": f"실행 서버 요청 실패: {response.status_code} - {response.text}"}
                    
                    # 응답 파싱
                    result = response.json()
                    logger.info(f"실행 서버 응답: {result}")
                    return result
                
                except requests.exceptions.RequestException as e:
                    if retry < max_retries - 1:
                        logger.warning(f"실행 서버 연결 오류 (재시도 {retry+1}/{max_retries}): {e}")
                        time.sleep(1)  # 재시도 전 대기
                        continue
                    return {"status": "error", "message": f"실행 서버 연결 오류: {e}"}
            
            # 모든 재시도 실패 시
            return {"status": "error", "message": "최대 재시도 횟수 초과"}
        
        except Exception as e:
            logger.exception(f"요청 처리 중 오류 발생: {e}")
            return {"status": "error", "message": f"요청 처리 중 오류 발생: {str(e)}"}


# 기본 사용 예시
if __name__ == "__main__":
    from config_loader import ConfigLoader
    
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 설정 로드
    config = ConfigLoader()
    execution_config = config.get_execution_server_config()
    
    # 실행 클라이언트 생성
    client = ExecutionClient(
        execution_config["url"],
        execution_config["api_key"]
    )
    
    # 테스트 신호 전송
    response = client.send_open_position(
        "BTCUSDT",
        "long",
        {"Answer": "yes", "Reason": "테스트 결정"}
    )
    
    print(f"응답: {response}")