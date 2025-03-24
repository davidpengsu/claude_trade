import json
import logging
import os
import time
from typing import Dict, Any, Optional

from bybit_client import BybitClient
from data_collector import DataCollector
from claude_client import ClaudeClient
from config_loader import ConfigLoader
from execution_client import ExecutionClient

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/decision_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("decision_manager")


class DecisionManager:
    """
    거래 결정 관리 클래스
    
    웹훅에서 오는 신호를 기반으로 거래 결정을 하고,
    Claude AI를 통해 결정을 검증한 후 실행 서버에 전달합니다.
    """
    
    def __init__(self):
        """DecisionManager 초기화"""
        # 설정 로드
        self.config = ConfigLoader()
        self.settings = self.config.load_config("system_settings.json")
        
        # Claude 클라이언트 초기화 (공유)
        claude_config = self.config.get_claude_api_key()
        self.claude_client = ClaudeClient(
            claude_config["key"],
            claude_config["model"]
        )
        
        # 실행 서버 클라이언트 초기화
        execution_config = self.config.get_execution_server_config()
        self.execution_client = ExecutionClient(
            execution_config["url"],
            execution_config["api_key"]
        )
        
        # 코인별 Bybit 클라이언트 및 데이터 수집기 초기화
        self.bybit_clients = {}
        self.data_collectors = {}
        
        for symbol in self.settings.get("symbols", []):
            # 코인 심볼에서 기본 코인 이름 추출 (예: BTCUSDT -> BTC)
            coin_base = symbol.replace("USDT", "")
            
            # 해당 코인의 API 키로 Bybit 클라이언트 초기화
            bybit_config = self.config.get_bybit_api_key(symbol)
            bybit_client = BybitClient(
                bybit_config["key"],
                bybit_config["secret"]
            )
            
            # 클라이언트 및 데이터 수집기 저장
            self.bybit_clients[symbol] = bybit_client
            self.data_collectors[symbol] = DataCollector(bybit_client)
        
        # 기타 설정 값
        self.retry_attempts = int(self.settings.get("retry_attempts", 3))
        self.retry_delay_seconds = int(self.settings.get("retry_delay_seconds", 30))
    
    def get_bybit_client(self, symbol: str) -> BybitClient:
        """
        특정 심볼의 Bybit 클라이언트 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            해당 심볼의 Bybit 클라이언트
        """
        if symbol not in self.bybit_clients:
            raise ValueError(f"지원하지 않는 심볼입니다: {symbol}")
        
        return self.bybit_clients[symbol]
    
    def get_data_collector(self, symbol: str) -> DataCollector:
        """
        특정 심볼의 데이터 수집기 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            해당 심볼의 데이터 수집기
        """
        if symbol not in self.data_collectors:
            raise ValueError(f"지원하지 않는 심볼입니다: {symbol}")
        
        return self.data_collectors[symbol]
    
    def get_active_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        특정 심볼의 활성 포지션 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            포지션 정보 또는 None
        """
        # 해당 심볼의 Bybit 클라이언트 조회
        bybit_client = self.get_bybit_client(symbol)
        
        # 바이비트 API를 통해 현재 포지션 조회
        position = bybit_client.get_positions(symbol)
        
        # 포지션이 없으면 None 반환
        if not position.get("exists", False):
            return None
        
        return position
    
    def handle_open_position(self, symbol: str, position_type: str) -> Dict[str, Any]:
        """
        포지션 진입 웹훅 처리
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position_type: 포지션 타입 ("long" 또는 "short")
            
        Returns:
            처리 결과
        """
        # 대소문자 통일
        position_type = position_type.lower()
        logger.info(f"{symbol} {position_type} 포지션 진입 신호 수신")
        
        try:
            # 현재 포지션 확인
            current_position = self.get_active_position(symbol)
            
            # 시장 데이터 수집
            data_collector = self.get_data_collector(symbol)
            market_data = data_collector.get_market_data(symbol)
            
            if not market_data:
                return {"status": "error", "message": "시장 데이터 수집 실패"}
            
            # 시장 데이터에서 현재 가격 추출
            current_price = market_data.current_price
            if current_price is None:
                return {"status": "error", "message": "현재 가격 조회 실패"}
            
            # 1. 포지션이 없는 경우
            if current_position is None:
                # Claude AI에게 진입 적절성 검증 요청
                ai_decision = self.claude_client.verify_entry(symbol, position_type, market_data)
                
                if ai_decision.get("Answer") == "yes":
                    logger.info(f"{symbol} {position_type} 포지션 진입 결정 (AI 승인)")
                    
                    # 실행 서버에 신호 전송
                    execution_result = self.execution_client.send_open_position(
                        symbol, 
                        position_type,
                        ai_decision
                    )
                    
                    if execution_result.get("status") == "success":
                        return {
                            "status": "success",
                            "message": f"{symbol} {position_type} 포지션 진입 신호 전송 성공",
                            "ai_decision": ai_decision
                        }
                    else:
                        return {
                            "status": "error",
                            "message": f"실행 서버 통신 오류: {execution_result.get('message')}",
                            "ai_decision": ai_decision
                        }
                    
                else:
                    logger.info(f"{symbol} {position_type} 포지션 진입 거부 (AI 거부)")
                    reason = ai_decision.get("Reason", "알 수 없는 이유")
                    return {"status": "rejected", "message": f"AI가 진입을 거부함: {reason}", "ai_decision": ai_decision}
            
            # 2. 현재 포지션이 있는 경우 (방향은 다를 수 있음)
            else:
                current_side = current_position.get("position_type")
                
                # 2.1. 동일한 방향의 포지션이 이미 있는 경우
                if current_side == position_type:
                    logger.info(f"이미 {symbol} {position_type} 포지션이 있습니다")
                    return {"status": "skipped", "message": f"이미 {position_type} 포지션이 있습니다"}
                
                # 2.2. 반대 방향의 포지션이 있는 경우
                logger.info(f"{symbol} 반대 방향({current_side}) 포지션이 있어 청산 후 {position_type} 진입 필요")
                
                # 먼저 기존 포지션 청산 신호 전송 (Java 코드와 동일하게 먼저 청산)
                close_result = self.execution_client.send_close_position(
                    symbol,
                    current_position
                )

                if close_result.get("status") != "success":
                    return {
                        "status": "error",
                        "message": f"기존 포지션({current_side}) 청산 신호 전송 실패: {close_result.get('message')}"
                    }

                # 청산 신호 전송 후 AI에게 새 포지션 진입 검증 요청
                ai_decision = self.claude_client.verify_entry(symbol, position_type, market_data)

                if ai_decision.get("Answer") != "yes":
                    logger.info(f"{symbol} {position_type} 포지션 진입 거부 (AI 거부)")
                    reason = ai_decision.get("Reason", "알 수 없는 이유")
                    return {
                        "status": "partial",
                        "message": f"기존 포지션({current_side}) 청산 신호 전송 완료. 새 진입({position_type}) AI 거부: {reason}",
                        "ai_decision": ai_decision
                    }

                # AI 승인 시 새 포지션 진입 신호 전송
                open_result = self.execution_client.send_open_position(
                    symbol, 
                    position_type,
                    ai_decision
                )

                if open_result.get("status") == "success":
                    return {
                        "status": "success",
                        "message": f"{symbol} 포지션 전환 신호 전송 성공 ({current_side} 청산 → {position_type} 진입)",
                        "ai_decision": ai_decision
                    }
                else:
                    return {
                        "status": "partial",
                        "message": f"기존 포지션({current_side}) 청산 완료. 새 포지션({position_type}) 진입 신호 전송 실패: {open_result.get('message')}",
                        "ai_decision": ai_decision
                    }
                
        except Exception as e:
            logger.exception(f"{symbol} {position_type} 포지션 진입 결정 중 오류 발생: {e}")
            return {"status": "error", "message": f"포지션 진입 결정 중 오류 발생: {str(e)}"}
    
    def handle_close_position(self, symbol: str) -> Dict[str, Any]:
        """
        포지션 청산 웹훅 처리
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            처리 결과
        """
        logger.info(f"{symbol} 포지션 청산 신호 수신")
        
        try:
            # 현재 포지션 확인
            current_position = self.get_active_position(symbol)
            
            if not current_position:
                logger.info(f"{symbol} 활성 포지션이 없습니다")
                return {"status": "skipped", "message": f"{symbol} 포지션이 없습니다"}
            
            # 실행 서버에 청산 신호 전송
            execution_result = self.execution_client.send_close_position(
                symbol,
                current_position
            )
            
            if execution_result.get("status") == "success":
                return {
                    "status": "success",
                    "message": f"{symbol} {current_position.get('position_type')} 포지션 청산 신호 전송 성공"
                }
            else:
                return {
                    "status": "error",
                    "message": f"실행 서버 통신 오류: {execution_result.get('message')}"
                }
                
        except Exception as e:
            logger.exception(f"{symbol} 포지션 청산 결정 중 오류 발생: {e}")
            return {"status": "error", "message": f"포지션 청산 결정 중 오류 발생: {str(e)}"}
    
    def handle_trend_touch(self, symbol: str) -> Dict[str, Any]:
        """
        추세선 터치 웹훅 처리
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            처리 결과
        """
        logger.info(f"{symbol} 추세선 터치 신호 수신")
        
        try:
            # 현재 포지션 확인
            current_position = self.get_active_position(symbol)
            
            if not current_position:
                logger.info(f"{symbol} 활성 포지션이 없습니다")
                return {"status": "skipped", "message": f"{symbol} 포지션이 없습니다"}
            
            # 현재 가격 확인
            bybit_client = self.get_bybit_client(symbol)
            current_price = bybit_client.get_current_price(symbol)
            entry_price = current_position.get("entry_price", 0)
            
            # 가격 변동률 계산
            change_rate = ((current_price - entry_price) / entry_price) * 100
            logger.info(f"가격 변동률: {change_rate:.2f}%")
            
            # 변동률이 3.3% 미만이면 처리하지 않음 (Java 코드와 동일하게 추가)
            if abs(change_rate) < 3.3:
                logger.info(f"가격 변동률이 임계값(3.3%) 미만, 작업 건너뜀")
                return {
                    "status": "skipped", 
                    "message": "가격 변동률이 임계값(3.3%) 미만이므로 분석하지 않음",
                    "change_rate": f"{change_rate:.2f}%"
                }
            
            # 시장 데이터 수집
            data_collector = self.get_data_collector(symbol)
            market_data = data_collector.get_market_data(symbol)
            
            if not market_data:
                return {"status": "error", "message": "시장 데이터 수집 실패"}
            
            # Claude AI에게 포지션 유지/청산 적절성 검증 요청
            trend_type = "상승" if current_position.get("position_type") == "long" else "하락"
            ai_decision = self.claude_client.verify_trend_touch(symbol, current_position, trend_type, market_data)
            
            if ai_decision.get("Answer") == "yes":  # yes = 청산
                logger.info(f"{symbol} {current_position.get('position_type')} 포지션 청산 결정 (AI 승인)")
                
                # 실행 서버에 청산 신호 전송
                execution_result = self.execution_client.send_trend_touch_decision(
                    symbol,
                    current_position,
                    ai_decision
                )
                
                if execution_result.get("status") == "success":
                    return {
                        "status": "success",
                        "message": f"{symbol} {current_position.get('position_type')} 포지션 청산 신호 전송 성공 (추세선 터치)",
                        "ai_decision": ai_decision,
                        "change_rate": f"{change_rate:.2f}%"
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"실행 서버 통신 오류: {execution_result.get('message')}",
                        "ai_decision": ai_decision,
                        "change_rate": f"{change_rate:.2f}%"
                    }
            else:
                logger.info(f"{symbol} {current_position.get('position_type')} 포지션 유지 결정 (AI 권장)")
                reason = ai_decision.get("Reason", "알 수 없는 이유")
                return {
                    "status": "maintain", 
                    "message": f"AI 결정: 포지션 유지 - {reason}",
                    "ai_decision": ai_decision,
                    "change_rate": f"{change_rate:.2f}%"
                }
                
        except Exception as e:
            logger.exception(f"{symbol} 추세선 터치 결정 중 오류 발생: {e}")
            return {"status": "error", "message": f"추세선 터치 결정 중 오류 발생: {str(e)}"}


# 기본 사용 예시
if __name__ == "__main__":
    # 결정 매니저 생성
    manager = DecisionManager()
    
    # 특정 심볼의 포지션 확인
    symbol = "BTCUSDT"
    position = manager.get_active_position(symbol)
    if position:
        print(f"{symbol} 활성 포지션: {position.get('position_type')}, 크기: {position.get('size')}")
    else:
        print(f"{symbol} 활성 포지션 없음")
    
    # 진입 결정 테스트
    result = manager.handle_open_position("BTCUSDT", "long")
    print(f"진입 결정 결과: {result}")