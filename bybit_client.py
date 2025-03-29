import hmac
import hashlib
import json
import time
import logging
import math
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Dict, Any, Optional, List, Union, Tuple

import requests


class BybitClient:
    """
    Bybit API 클라이언트
    
    Bybit V5 API와 상호작용하기 위한 클래스
    """
    BASE_URL = "https://api.bybit.com"
    
    def __init__(self, api_key: str, api_secret: str):
        """
        BybitClient 초기화
        
        Args:
            api_key: Bybit API 키
            api_secret: Bybit API 시크릿
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        
        # 로거 설정
        self.logger = logging.getLogger("bybit_client")
        self.logger.setLevel(logging.INFO)
    
    def get_kline_data(self, symbol: str, interval: str, limit: int = 200) -> Dict[str, Any]:
        """
        K-line (캔들스틱) 데이터 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            interval: 시간 간격 (1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, M, W)
            limit: 조회할 캔들 수 (최대 1000)
            
        Returns:
            K-line 데이터를 포함한 응답
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        
        self.logger.info(f"{symbol} {interval}분봉 데이터 {limit}개 요청...")
        return self._send_get_request("/v5/market/kline", params)
    
    def get_order_book(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """
        오더북 데이터 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            limit: 오더북 깊이 (최대 200)
            
        Returns:
            오더북 데이터를 포함한 응답
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "limit": min(limit, 100)
        }
        
        return self._send_get_request("/v5/market/orderbook", params)
    
    def get_positions(self, symbol: str) -> Dict[str, Any]:
        """
        현재 포지션 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            포지션 정보를 포함한 응답
        """
        params = {
            "category": "linear",
            "symbol": symbol
        }
        
        response = self._send_get_request("/v5/position/list", params, True)
        
        # 포지션 정보 확인 및 처리
        if response.get("retCode") == 0:
            positions = response.get("result", {}).get("list", [])
            # 활성 상태인 포지션만 필터링
            active_positions = [pos for pos in positions if self.safe_float_conversion(pos.get("size", 0)) > 0]
            
            if active_positions:
                position = active_positions[0]
                result = {
                    "exists": True,
                    "size": self.safe_float_conversion(position.get("size", 0)),
                    "side": position.get("side"),  # Buy 또는 Sell
                    "entry_price": self.safe_float_conversion(position.get("avgPrice", 0)),
                    "leverage": self.safe_float_conversion(position.get("leverage", 1)),
                    "unrealized_pnl": self.safe_float_conversion(position.get("unrealisedPnl", 0)),
                    "take_profit": self.safe_float_conversion(position.get("takeProfit", 0)),
                    "stop_loss": self.safe_float_conversion(position.get("stopLoss", 0))
                }
                result["position_type"] = "long" if result["side"] == "Buy" else "short"
                return result
        
        # 포지션이 없거나 오류 발생 시
        return {
            "exists": False,
            "size": 0,
            "side": None,
            "position_type": None
        }
    
    def get_current_price(self, symbol: str) -> float:
        """
        현재 티커 가격 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            현재 가격 (float)
        """
        params = {
            "category": "linear",
            "symbol": symbol
        }
        
        response = self._send_get_request("/v5/market/tickers", params)
        
        if response.get("retCode") == 0:
            tickers = response.get("result", {}).get("list", [])
            if tickers:
                return self.safe_float_conversion(tickers[0].get("lastPrice", 0))
        
        raise Exception(f"현재 가격 조회 실패: {response}")
    
    def _send_get_request(self, endpoint: str, params: Dict[str, Any], requires_auth: bool = False) -> Dict[str, Any]:
        """
        Bybit API에 GET 요청 전송
        
        Args:
            endpoint: API 엔드포인트
            params: 쿼리 파라미터
            requires_auth: 인증이 필요한지 여부
            
        Returns:
            API 응답
        """
        url = self.BASE_URL + endpoint
        
        # 인증이 필요한 경우 헤더 추가
        headers = {}
        if requires_auth:
            timestamp = int(time.time() * 1000)
            recv_window = "5000"
            
            # 쿼리 문자열 생성
            query_string = "&".join([f"{key}={params[key]}" for key in sorted(params.keys())])
            
            # 서명 생성
            sign_string = f"{timestamp}{self.api_key}{recv_window}{query_string}"
            signature = hmac.new(
                self.api_secret.encode(),
                sign_string.encode(),
                hashlib.sha256
            ).hexdigest()
            
            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": str(timestamp),
                "X-BAPI-RECV-WINDOW": recv_window,
                "X-BAPI-SIGN": signature
            }
        
        # 최대 3번 재시도
        max_retries = 3
        for retry in range(max_retries):
            try:
                # 요청 전송
                response = self.session.get(url, params=params, headers=headers)
                
                # 응답 확인
                if response.status_code != 200:
                    if retry < max_retries - 1:
                        self.logger.warning(f"API 요청 실패 (재시도 {retry+1}/{max_retries}): {response.status_code} - {response.text}")
                        time.sleep(1)  # 재시도 전 대기
                        continue
                    raise Exception(f"API 요청 실패: {response.status_code} - {response.text}")
                
                return response.json()
            except Exception as e:
                if retry < max_retries - 1:
                    self.logger.warning(f"API 요청 중 오류 발생 (재시도 {retry+1}/{max_retries}): {e}")
                    time.sleep(1)  # 재시도 전 대기
                    continue
                raise
        
        # 모든 재시도 실패 시
        raise Exception("API 요청 실패: 최대 재시도 횟수 초과")
    
    def _send_post_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bybit API에 POST 요청 전송
        
        Args:
            endpoint: API 엔드포인트
            params: 요청 파라미터
            
        Returns:
            API 응답
        """
        url = self.BASE_URL + endpoint
        timestamp = int(time.time() * 1000)
        recv_window = "5000"
        
        # JSON으로 변환
        json_params = json.dumps(params)
        
        # 서명 생성
        sign_string = f"{timestamp}{self.api_key}{recv_window}{json_params}"
        signature = hmac.new(
            self.api_secret.encode(),
            sign_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # 헤더 설정
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": recv_window,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json"
        }
        
        # 최대 3번 재시도
        max_retries = 3
        for retry in range(max_retries):
            try:
                # 요청 전송
                response = self.session.post(url, data=json_params, headers=headers)
                
                # 응답 확인
                if response.status_code != 200:
                    if retry < max_retries - 1:
                        self.logger.warning(f"API 요청 실패 (재시도 {retry+1}/{max_retries}): {response.status_code} - {response.text}")
                        time.sleep(1)  # 재시도 전 대기
                        continue
                    raise Exception(f"API 요청 실패: {response.status_code} - {response.text}")
                
                return response.json()
            except Exception as e:
                if retry < max_retries - 1:
                    self.logger.warning(f"API 요청 중 오류 발생 (재시도 {retry+1}/{max_retries}): {e}")
                    time.sleep(1)  # 재시도 전 대기
                    continue
                raise
        
        # 모든 재시도 실패 시
        raise Exception("API 요청 실패: 최대 재시도 횟수 초과")
    
    @staticmethod
    def safe_float_conversion(value: Optional[Union[str, int, float]]) -> float:
        """
        값을 안전하게 float로 변환
        
        Args:
            value: 변환할 값 (문자열, 정수, 실수 또는 None)
            
        Returns:
            변환된 float 값 또는 변환 실패 시 0.0
        """
        if value is None or value == "":
            return 0.0
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0