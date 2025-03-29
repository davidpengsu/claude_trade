import threading
import time
import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

from config_loader import ConfigLoader

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/position_monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("position_monitor")


class PositionMonitor:
    """
    포지션 모니터링 클래스
    
    활성 포지션의 TP/SL 조건을 모니터링하고 조건 충족 시 포지션 청산 신호를 전송
    """
    
    def __init__(self, decision_manager, check_interval: float = 1.0):
        """
        PositionMonitor 초기화
        
        Args:
            decision_manager: DecisionManager 인스턴스
            check_interval: 확인 간격(초)
        """
        self.decision_manager = decision_manager
        self.check_interval = check_interval
        self.running = False
        self.monitor_thread = None
        
        # 설정 로드
        self.config = ConfigLoader()
        self.settings = self.config.load_config("system_settings.json")
        
        # 심볼 목록
        self.symbols = self.settings.get("symbols", [])
        
        # TP/SL 설정
        self.tp_percent = self.settings.get("tp_percent", 30.0)
        self.sl_percent = self.settings.get("sl_percent", 2.5)
        
        # 모니터링 중인 포지션 캐시
        # 구조: {symbol: {"entry_price": float, "position_type": str, "tp_price": float, "sl_price": float}}
        self.monitored_positions = {}
        
        logger.info(f"포지션 모니터 초기화 완료 (TP: {self.tp_percent}%, SL: {self.sl_percent}%)")
    
    def start(self):
        """모니터링 시작"""
        if self.running:
            logger.warning("포지션 모니터가 이미 실행 중입니다")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.info("포지션 모니터링 시작")
    
    def stop(self):
        """모니터링 중지"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        logger.info("포지션 모니터링 중지")
    
    def _monitor_loop(self):
        """
        포지션 모니터링 루프
        
        지속적으로 모든 심볼의 활성 포지션을 확인하고 TP/SL 조건 충족 시 청산 신호 전송
        """
        while self.running:
            try:
                # 모든 심볼 확인
                for symbol in self.symbols:
                    self._check_position(symbol)
                
                # 지정된 간격만큼 대기
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"모니터링 중 오류 발생: {e}")
                time.sleep(5)  # 오류 발생 시 5초 대기 후 재시도
    
    def _check_position(self, symbol: str):
        """
        특정 심볼의 포지션 확인
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
        """
        try:
            # 현재 포지션 확인
            position = self.decision_manager.get_active_position(symbol)
            
            # 포지션이 없는 경우
            if not position or not position.get("exists", False):
                # 이전에 모니터링 중이던 포지션이면 캐시에서 제거
                if symbol in self.monitored_positions:
                    logger.info(f"{symbol} 포지션이 종료되어 모니터링 중단")
                    del self.monitored_positions[symbol]
                return
            
            # 현재 시장 가격 조회
            current_price = self.decision_manager.get_bybit_client(symbol).get_current_price(symbol)
            if not current_price:
                logger.warning(f"{symbol} 현재 가격 조회 실패")
                return
            
            position_type = position.get("position_type")  # "long" 또는 "short"
            entry_price = position.get("entry_price")
            
            # 새 포지션이거나 진입가가 변경된 경우 TP/SL 가격 계산
            if (symbol not in self.monitored_positions or 
                self.monitored_positions[symbol]["entry_price"] != entry_price or
                self.monitored_positions[symbol]["position_type"] != position_type):
                
                # TP/SL 가격 계산
                tp_price, sl_price = self._calculate_tp_sl(position_type, entry_price)
                
                # 모니터링 캐시 업데이트
                self.monitored_positions[symbol] = {
                    "entry_price": entry_price,
                    "position_type": position_type,
                    "tp_price": tp_price,
                    "sl_price": sl_price
                }
                
                logger.info(f"{symbol} {position_type} 포지션 모니터링 시작: 진입가={entry_price}, TP={tp_price}, SL={sl_price}")
            
            # 캐시에서 TP/SL 가격 가져오기
            tp_price = self.monitored_positions[symbol]["tp_price"]
            sl_price = self.monitored_positions[symbol]["sl_price"]
            
            # TP/SL 조건 확인
            if position_type == "long":
                # 롱 포지션: 가격이 TP 이상이거나 SL 이하인 경우 청산
                if current_price >= tp_price:
                    logger.info(f"{symbol} 롱 포지션 TP 도달 (현재가: {current_price}, TP: {tp_price})")
                    self._send_close_signal(symbol, "TP")
                    return
                elif current_price <= sl_price:
                    logger.info(f"{symbol} 롱 포지션 SL 도달 (현재가: {current_price}, SL: {sl_price})")
                    self._send_close_signal(symbol, "SL")
                    return
            else:  # short
                # 숏 포지션: 가격이 TP 이하이거나 SL 이상인 경우 청산
                if current_price <= tp_price:
                    logger.info(f"{symbol} 숏 포지션 TP 도달 (현재가: {current_price}, TP: {tp_price})")
                    self._send_close_signal(symbol, "TP")
                    return
                elif current_price >= sl_price:
                    logger.info(f"{symbol} 숏 포지션 SL 도달 (현재가: {current_price}, SL: {sl_price})")
                    self._send_close_signal(symbol, "SL")
                    return
                
        except Exception as e:
            logger.error(f"{symbol} 포지션 확인 중 오류 발생: {e}")
    
    def _calculate_tp_sl(self, position_type: str, entry_price: float):
        """
        TP/SL 가격 계산
        
        Args:
            position_type: 포지션 타입 ("long" 또는 "short")
            entry_price: 진입 가격
            
        Returns:
            (TP 가격, SL 가격) 튜플
        """
        if position_type == "long":
            tp_price = entry_price * (1 + self.tp_percent / 100)
            sl_price = entry_price * (1 - self.sl_percent / 100)
        else:  # short
            tp_price = entry_price * (1 - self.tp_percent / 100)
            sl_price = entry_price * (1 + self.sl_percent / 100)
        
        return tp_price, sl_price
    
    def _send_close_signal(self, symbol: str, reason: str):
        """
        포지션 청산 신호 전송 (실행 서버에 신호만 전송)
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            reason: 청산 이유 ("TP" 또는 "SL")
        """
        try:
            # 청산 이유 기록
            logger.info(f"{symbol} 포지션 {reason} 도달로 청산 신호 전송 중")
            
            # decision_manager를 통해 실행 서버에 청산 신호 전송
            result = self.decision_manager.handle_close_position(symbol)
            
            # 청산 신호 전송 결과 로깅
            if result.get("status") == "success":
                logger.info(f"{symbol} 포지션 청산 신호 전송 성공 ({reason})")
            else:
                logger.error(f"{symbol} 포지션 청산 신호 전송 실패 ({reason}): {result.get('message')}")
            
            # 모니터링 캐시에서 제거 (청산 실패하더라도 다음 주기에 다시 확인)
            if symbol in self.monitored_positions:
                del self.monitored_positions[symbol]
                
        except Exception as e:
            logger.error(f"{symbol} 포지션 청산 신호 전송 중 오류 발생: {e}")


# 메인 함수 (테스트용)
if __name__ == "__main__":
    from decision_manager import DecisionManager
    
    # 결정 매니저 생성
    dm = DecisionManager()
    
    # 포지션 모니터 생성 및 시작
    monitor = PositionMonitor(dm)
    monitor.start()
    
    try:
        # 계속 실행
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # Ctrl+C로 종료 시 모니터 중지
        monitor.stop()
        print("프로그램 종료")