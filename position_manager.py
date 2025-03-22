import json
import logging
import os
import time
import uuid
from typing import Dict, Any, List, Optional, Union, Tuple
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from dataclasses import dataclass

from bybit_client import BybitClient
from data_collector import DataCollector
from claude_client import ClaudeClient
from config_loader import ConfigLoader

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/position_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("position_manager")

@dataclass
class TradeLog:
    """거래 로그 정보"""
    trade_id: str
    symbol: str
    position_type: str  # 'long' 또는 'short'
    entry_price: float
    entry_time: int
    leverage: int
    size: float
    reason: str
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    exit_price: Optional[float] = None
    exit_time: Optional[int] = None
    pnl: Optional[float] = None
    exit_reason: Optional[str] = None
    status: str = "open"  # 'open' 또는 'closed'


class PositionManager:
    """
    포지션 관리 클래스
    
    웹훅에서 오는 신호를 기반으로 포지션을 관리하고,
    Claude AI를 통해 포지션 진입/청산 결정을 검증합니다.
    """
    
    def __init__(self):
        """PositionManager 초기화"""
        # 설정 로드
        self.config = ConfigLoader()
        self.api_keys = self.config.load_config("api_keys.json")
        self.settings = self.config.load_config("system_settings.json")
        
        # Bybit 클라이언트 초기화
        self.bybit_client = BybitClient(
            self.api_keys["bybit_api"]["key"],
            self.api_keys["bybit_api"]["secret"]
        )
        
        # 데이터 수집기 초기화
        self.data_collector = DataCollector(self.bybit_client)
        
        # Claude 클라이언트 초기화
        self.claude_client = ClaudeClient(
            self.api_keys["claude_api"]["key"],
            self.api_keys["claude_api"]["model"]
        )
        
        # 거래 로그 관리
        self.trade_logs = {}  # trade_id -> TradeLog 매핑
        self.load_trade_logs()  # 저장된 거래 로그 불러오기
        
        # 포지션 사이즈 설정
        self.position_size_mode = self.settings.get("position_size_mode", "percent")  # "fixed" 또는 "percent"
        self.position_size_fixed = float(self.settings.get("position_size_fixed", 100.0))  # 고정 금액
        self.position_size_percent = float(self.settings.get("position_size_percent", 10.0))  # 백분율
        
        # 기타 설정 값
        self.leverage = int(self.settings.get("leverage", 5))
        self.sl_percent = float(self.settings.get("sl_percent", 1.5))
        self.tp_percent = float(self.settings.get("tp_percent", 3.0))
        self.retry_attempts = int(self.settings.get("retry_attempts", 3))
        self.retry_delay_seconds = int(self.settings.get("retry_delay_seconds", 30))
        self.reverse_trading = bool(self.settings.get("test_mode", False))
    
    def load_trade_logs(self):
        """저장된 거래 로그 로드"""
        logs_file = "data/trade_logs.json"
        if os.path.exists(logs_file):
            try:
                with open(logs_file, 'r', encoding='utf-8') as f:
                    logs_data = json.load(f)
                
                for trade_id, log_data in logs_data.items():
                    self.trade_logs[trade_id] = TradeLog(
                        trade_id=trade_id,
                        symbol=log_data.get("symbol"),
                        position_type=log_data.get("position_type"),
                        entry_price=log_data.get("entry_price"),
                        entry_time=log_data.get("entry_time"),
                        leverage=log_data.get("leverage"),
                        size=log_data.get("size"),
                        reason=log_data.get("reason"),
                        tp_price=log_data.get("tp_price"),
                        sl_price=log_data.get("sl_price"),
                        exit_price=log_data.get("exit_price"),
                        exit_time=log_data.get("exit_time"),
                        pnl=log_data.get("pnl"),
                        exit_reason=log_data.get("exit_reason"),
                        status=log_data.get("status", "open")
                    )
                
                # 활성 거래 수 계산
                active_trades = [log for log in self.trade_logs.values() if log.status == "open"]
                logger.info(f"거래 로그 로드 완료: 총 {len(self.trade_logs)}개, 활성 {len(active_trades)}개")
            except Exception as e:
                logger.error(f"거래 로그 로드 중 오류 발생: {e}")
    
    def save_trade_logs(self):
        """현재 거래 로그 저장"""
        logs_data = {}
        for trade_id, log in self.trade_logs.items():
            logs_data[trade_id] = {
                "symbol": log.symbol,
                "position_type": log.position_type,
                "entry_price": log.entry_price,
                "entry_time": log.entry_time,
                "leverage": log.leverage,
                "size": log.size,
                "reason": log.reason,
                "tp_price": log.tp_price,
                "sl_price": log.sl_price,
                "exit_price": log.exit_price,
                "exit_time": log.exit_time,
                "pnl": log.pnl,
                "exit_reason": log.exit_reason,
                "status": log.status
            }
        
        try:
            with open("data/trade_logs.json", 'w', encoding='utf-8') as f:
                json.dump(logs_data, f, indent=4)
            logger.info("거래 로그 저장 완료")
        except Exception as e:
            logger.error(f"거래 로그 저장 중 오류 발생: {e}")
    
    def get_active_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        특정 심볼의 활성 포지션 조회 (바이비트 API 사용)
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            포지션 정보 또는 None
        """
        # 바이비트 API를 통해 현재 포지션 조회
        position = self.bybit_client.get_positions(symbol)
        
        # 포지션이 없으면 None 반환
        if not position.get("exists", False):
            return None
        
        return position
    
    def get_active_trade_log(self, symbol: str) -> Optional[TradeLog]:
        """
        특정 심볼의 활성 거래 로그 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            거래 로그 또는 None
        """
        # 해당 심볼의 활성 거래 로그 검색
        for log in self.trade_logs.values():
            if log.symbol == symbol and log.status == "open":
                return log
        
        return None
    
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
        
        # 현재 포지션 확인 (바이비트 API 사용)
        current_position = self.get_active_position(symbol)
        
        # 시장 데이터 수집
        market_data = self.data_collector.get_market_data(symbol)
        if not market_data:
            return {"status": "error", "message": "시장 데이터 수집 실패"}
        
        # 시장 데이터에서 현재 가격 추출
        current_price = market_data.current_price
        if current_price is None:
            return {"status": "error", "message": "현재 가격 조회 실패"}
        
        # 리버스 트레이딩 적용 (설정이 활성화된 경우)
        if self.reverse_trading:
            logger.info(f"리버스 트레이딩 모드 활성화: {position_type} -> {'short' if position_type == 'long' else 'long'}")
            position_type = "short" if position_type == "long" else "long"
        
        # 1. 포지션이 없는 경우
        if current_position is None:
            # Claude AI에게 진입 적절성 검증 요청
            ai_decision = self.claude_client.verify_entry(symbol, position_type, market_data)
            
            if ai_decision.get("Answer") == "yes":
                logger.info(f"{symbol} {position_type} 포지션 진입 결정 (AI 승인)")
                
                try:
                    # 레버리지 설정
                    self.bybit_client.set_leverage(symbol, self.leverage)
                    
                    # 주문 수량 계산
                    position_size_value = self.position_size_fixed if self.position_size_mode == "fixed" else self.position_size_percent
                    order_qty = self.bybit_client.calculate_order_quantity(
                        symbol=symbol,
                        position_size_mode=self.position_size_mode,
                        position_size_value=position_size_value,
                        leverage=self.leverage,
                        current_price=current_price
                    )
                    
                    # 매수/매도 방향 설정
                    side = "Buy" if position_type == "long" else "Sell"
                    
                    # 시장가 주문 실행
                    order_result = self.bybit_client.place_market_order(
                        symbol=symbol,
                        side=side,
                        qty=str(order_qty)
                    )
                    
                    if order_result.get("retCode") != 0:
                        logger.error(f"{symbol} 주문 실패: {order_result}")
                        return {"status": "error", "message": f"주문 실패: {order_result.get('retMsg', '알 수 없는 오류')}"}
                    
                    # 주문 ID 및 시간
                    order_id = order_result.get("result", {}).get("orderId")
                    order_time = int(time.time() * 1000)
                    
                    # 주문 체결 대기 (최대 5초)
                    time.sleep(2)
                    
                    # 현재 포지션 조회하여 진입가 확인
                    position = self.get_active_position(symbol)
                    if not position:
                        logger.warning(f"{symbol} 주문 후 포지션이 생성되지 않음")
                        return {"status": "error", "message": "주문은 성공했으나 포지션이 생성되지 않음"}
                    
                    entry_price = position.get("entry_price")
                    
                    # TP/SL 가격 계산
                    tp_price, sl_price = self._calculate_tp_sl(position_type, entry_price)
                    
                    # TP/SL 설정
                    self.bybit_client.set_tp_sl(symbol, tp_price, sl_price)
                    
                    # 거래 로그 생성
                    trade_id = str(uuid.uuid4())
                    trade_log = TradeLog(
                        trade_id=trade_id,
                        symbol=symbol,
                        position_type=position_type,
                        entry_price=entry_price,
                        entry_time=order_time,
                        leverage=self.leverage,
                        size=float(order_qty),
                        reason=ai_decision.get("Reason", "AI 승인"),
                        tp_price=tp_price,
                        sl_price=sl_price,
                        status="open"
                    )
                    
                    # 거래 로그 저장
                    self.trade_logs[trade_id] = trade_log
                    self.save_trade_logs()
                    
                    logger.info(f"{symbol} {position_type} 포지션 진입 완료: 수량={order_qty}, 진입가={entry_price}, TP={tp_price}, SL={sl_price}")
                    
                    return {
                        "status": "success",
                        "message": f"{symbol} {position_type} 포지션 진입 성공",
                        "trade_id": trade_id,
                        "entry_price": entry_price,
                        "size": order_qty,
                        "leverage": self.leverage,
                        "tp_price": tp_price,
                        "sl_price": sl_price
                    }
                    
                except Exception as e:
                    logger.exception(f"{symbol} {position_type} 포지션 진입 중 오류 발생: {e}")
                    return {"status": "error", "message": f"포지션 진입 중 오류 발생: {str(e)}"}
                
            else:
                logger.info(f"{symbol} {position_type} 포지션 진입 거부 (AI 거부)")
                reason = ai_decision.get("Reason", "알 수 없는 이유")
                return {"status": "rejected", "message": f"AI가 진입을 거부함: {reason}"}
        
        # 2. 현재 포지션이 있는 경우 (방향은 다를 수 있음)
        else:
            current_side = current_position.get("position_type")
            
            # 2.1. 동일한 방향의 포지션이 이미 있는 경우
            if current_side == position_type:
                logger.info(f"이미 {symbol} {position_type} 포지션이 있습니다")
                return {"status": "skipped", "message": f"이미 {position_type} 포지션이 있습니다"}
            
            # 2.2. 반대 방향의 포지션이 있는 경우
            logger.info(f"{symbol} 반대 방향({current_side}) 포지션이 있어 청산 후 {position_type} 진입 시도")
            
            # 기존 포지션 청산
            close_result = self.bybit_client.close_position(symbol)
            if not close_result:
                logger.error(f"{symbol} 포지션 청산 실패")
                return {"status": "error", "message": "기존 포지션 청산 실패"}
            
            # 관련 주문 모두 취소
            self.bybit_client.cancel_all_orders(symbol)
            
            # 기존 거래 로그 업데이트
            active_log = self.get_active_trade_log(symbol)
            if active_log:
                position_info = current_position  # 이미 위에서 조회한 포지션 정보 사용
                
                # 거래 종료 정보 업데이트
                active_log.exit_price = current_price
                active_log.exit_time = int(time.time() * 1000)
                active_log.exit_reason = f"반대 포지션({position_type}) 진입으로 청산"
                active_log.status = "closed"
                
                # PnL 계산
                if position_info.get("unrealized_pnl") is not None:
                    active_log.pnl = position_info.get("unrealized_pnl")
                
                # 거래 로그 저장
                self.save_trade_logs()
            
            # 새 포지션 진입 검증
            ai_decision = self.claude_client.verify_entry(symbol, position_type, market_data)
            
            if ai_decision.get("Answer") != "yes":
                logger.info(f"{symbol} {position_type} 포지션 진입 거부 (AI 거부)")
                reason = ai_decision.get("Reason", "알 수 없는 이유")
                return {
                    "status": "partial",
                    "message": f"기존 포지션 청산 완료. AI가 새 진입({position_type})을 거부함: {reason}"
                }
            
            # 여기서부터는 새 포지션 진입 로직 (위 1번과 유사)
            try:
                # 레버리지 설정
                self.bybit_client.set_leverage(symbol, self.leverage)
                
                # 주문 수량 계산
                position_size_value = self.position_size_fixed if self.position_size_mode == "fixed" else self.position_size_percent
                order_qty = self.bybit_client.calculate_order_quantity(
                    symbol=symbol,
                    position_size_mode=self.position_size_mode,
                    position_size_value=position_size_value,
                    leverage=self.leverage,
                    current_price=current_price
                )
                
                # 매수/매도 방향 설정
                side = "Buy" if position_type == "long" else "Sell"
                
                # 시장가 주문 실행
                order_result = self.bybit_client.place_market_order(
                    symbol=symbol,
                    side=side,
                    qty=str(order_qty)
                )
                
                if order_result.get("retCode") != 0:
                    logger.error(f"{symbol} 주문 실패: {order_result}")
                    return {"status": "partial", "message": f"기존 포지션 청산 완료. 새 주문 실패: {order_result.get('retMsg', '알 수 없는 오류')}"}
                
                # 주문 ID 및 시간
                order_id = order_result.get("result", {}).get("orderId")
                order_time = int(time.time() * 1000)
                
                # 주문 체결 대기 (최대 5초)
                time.sleep(2)
                
                # 현재 포지션 조회하여 진입가 확인
                position = self.get_active_position(symbol)
                if not position:
                    logger.warning(f"{symbol} 주문 후 포지션이 생성되지 않음")
                    return {"status": "partial", "message": "기존 포지션 청산 완료. 새 주문은 성공했으나 포지션이 생성되지 않음"}
                
                entry_price = position.get("entry_price")
                
                # TP/SL 가격 계산
                tp_price, sl_price = self._calculate_tp_sl(position_type, entry_price)
                
                # TP/SL 설정
                self.bybit_client.set_tp_sl(symbol, tp_price, sl_price)
                
                # 거래 로그 생성
                trade_id = str(uuid.uuid4())
                trade_log = TradeLog(
                    trade_id=trade_id,
                    symbol=symbol,
                    position_type=position_type,
                    entry_price=entry_price,
                    entry_time=order_time,
                    leverage=self.leverage,
                    size=float(order_qty),
                    reason=ai_decision.get("Reason", "AI 승인 (포지션 전환)"),
                    tp_price=tp_price,
                    sl_price=sl_price,
                    status="open"
                )
                
                # 거래 로그 저장
                self.trade_logs[trade_id] = trade_log
                self.save_trade_logs()
                
                logger.info(f"{symbol} {position_type} 포지션 전환 완료: 수량={order_qty}, 진입가={entry_price}, TP={tp_price}, SL={sl_price}")
                
                return {
                    "status": "success",
                    "message": f"기존 포지션 청산 후 {symbol} {position_type} 포지션 진입 성공",
                    "trade_id": trade_id,
                    "entry_price": entry_price,
                    "size": order_qty,
                    "leverage": self.leverage,
                    "tp_price": tp_price,
                    "sl_price": sl_price
                }
                
            except Exception as e:
                logger.exception(f"{symbol} {position_type} 포지션 전환 중 오류 발생: {e}")
                return {"status": "partial", "message": f"기존 포지션 청산 완료. 새 포지션 진입 중 오류 발생: {str(e)}"}
    
    def handle_close_position(self, symbol: str) -> Dict[str, Any]:
        """
        포지션 청산 웹훅 처리
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            처리 결과
        """
        logger.info(f"{symbol} 포지션 청산 신호 수신")
        
        # 현재 포지션 확인 (바이비트 API 사용)
        current_position = self.get_active_position(symbol)
        
        if not current_position:
            logger.info(f"{symbol} 활성 포지션이 없습니다")
            return {"status": "skipped", "message": f"{symbol} 포지션이 없습니다"}
        
        # 포지션 청산
        try:
            # 현재 포지션 정보 저장
            position_type = current_position.get("position_type")
            entry_price = current_position.get("entry_price")
            current_price = self.bybit_client.get_current_price(symbol)
            
            # 포지션 청산
            close_result = self.bybit_client.close_position(symbol)
            if not close_result:
                logger.error(f"{symbol} 포지션 청산 실패")
                return {"status": "error", "message": "포지션 청산 실패"}
            
            # 관련 주문 모두 취소
            self.bybit_client.cancel_all_orders(symbol)
            
            # 거래 로그 업데이트
            active_log = self.get_active_trade_log(symbol)
            if active_log:
                # 거래 종료 정보 업데이트
                active_log.exit_price = current_price
                active_log.exit_time = int(time.time() * 1000)
                active_log.exit_reason = "TP/SL 신호로 청산"
                active_log.status = "closed"
                
                # PnL 계산 (간략히 - 실제로는 수수료, 자금조달 비용 등 고려 필요)
                if position_type == "long":
                    pnl_ratio = (current_price - entry_price) / entry_price
                else:  # short
                    pnl_ratio = (entry_price - current_price) / entry_price
                
                active_log.pnl = pnl_ratio * active_log.size * entry_price * active_log.leverage
                
                # 거래 로그 저장
                self.save_trade_logs()
            
            logger.info(f"{symbol} {position_type} 포지션 청산 완료: 청산가={current_price}")
            
            return {
                "status": "success",
                "message": f"{symbol} {position_type} 포지션 청산 완료",
                "exit_price": current_price,
                "pnl": active_log.pnl if active_log else None
            }
            
        except Exception as e:
            logger.exception(f"{symbol} 포지션 청산 중 오류 발생: {e}")
            return {"status": "error", "message": f"포지션 청산 중 오류 발생: {str(e)}"}
    
    def handle_trend_touch(self, symbol: str) -> Dict[str, Any]:
        """
        추세선 터치 웹훅 처리
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            처리 결과
        """
        logger.info(f"{symbol} 추세선 터치 신호 수신")
        
        # 현재 포지션 확인 (바이비트 API 사용)
        current_position = self.get_active_position(symbol)
        
        if not current_position:
            logger.info(f"{symbol} 활성 포지션이 없습니다")
            return {"status": "skipped", "message": f"{symbol} 포지션이 없습니다"}
        
        # 시장 데이터 수집
        market_data = self.data_collector.get_market_data(symbol)
        if not market_data:
            return {"status": "error", "message": "시장 데이터 수집 실패"}
        
        # Claude AI에게 포지션 유지/청산 적절성 검증 요청
        trend_type = "상승" if current_position.get("position_type") == "long" else "하락"
        ai_decision = self.claude_client.verify_trend_touch(symbol, current_position, trend_type, market_data)
        
        if ai_decision.get("Answer") == "yes":  # yes = 청산
            logger.info(f"{symbol} {current_position.get('position_type')} 포지션 청산 결정 (AI 승인)")
            
            try:
                # 현재 포지션 정보 저장
                position_type = current_position.get("position_type")
                entry_price = current_position.get("entry_price")
                current_price = self.bybit_client.get_current_price(symbol)
                
                # 포지션 청산
                close_result = self.bybit_client.close_position(symbol)
                if not close_result:
                    logger.error(f"{symbol} 포지션 청산 실패")
                    return {"status": "error", "message": "포지션 청산 실패"}
                
                # 관련 주문 모두 취소
                self.bybit_client.cancel_all_orders(symbol)
                
                # 거래 로그 업데이트
                active_log = self.get_active_trade_log(symbol)
                if active_log:
                    # 거래 종료 정보 업데이트
                    active_log.exit_price = current_price
                    active_log.exit_time = int(time.time() * 1000)
                    active_log.exit_reason = "추세선 터치로 청산 (AI 결정)"
                    active_log.status = "closed"
                    
                    # PnL 계산 (간략히 - 실제로는 수수료, 자금조달 비용 등 고려 필요)
                    if position_type == "long":
                        pnl_ratio = (current_price - entry_price) / entry_price
                    else:  # short
                        pnl_ratio = (entry_price - current_price) / entry_price
                    
                    active_log.pnl = pnl_ratio * active_log.size * entry_price * active_log.leverage
                    
                    # 거래 로그 저장
                    self.save_trade_logs()
                
                logger.info(f"{symbol} {position_type} 포지션 청산 완료 (추세선 터치): 청산가={current_price}")
                
                return {
                    "status": "success",
                    "message": f"{symbol} {position_type} 포지션 청산 완료 (추세선 터치)",
                    "exit_price": current_price,
                    "pnl": active_log.pnl if active_log else None,
                    "reason": ai_decision.get("Reason", "AI 청산 결정")
                }
                
            except Exception as e:
                logger.exception(f"{symbol} 포지션 청산 중 오류 발생: {e}")
                return {"status": "error", "message": f"포지션 청산 중 오류 발생: {str(e)}"}
        else:
            logger.info(f"{symbol} {current_position.get('position_type')} 포지션 유지 결정 (AI 권장)")
            reason = ai_decision.get("Reason", "알 수 없는 이유")
            return {"status": "maintain", "message": f"AI 결정: 포지션 유지 - {reason}"}
    
    def _calculate_tp_sl(self, position_type: str, entry_price: float) -> Tuple[float, float]:
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