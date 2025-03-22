import json
import os
import math
from typing import Dict, Any, List, Optional
import time
from dataclasses import dataclass

from bybit_client import BybitClient
from technical_indicators import TechnicalIndicators, Chart
from config_loader import ConfigLoader


@dataclass
class Indicator:
    """통합 시장 지표 모델"""
    # 5분봉 데이터
    timestamp_5m: int
    datetime_5m: str
    open_5m: float
    close_5m: float
    high_5m: float
    low_5m: float
    volume_5m: float
    
    # 15분봉 데이터
    timestamp_15m: int
    datetime_15m: str
    open_15m: float
    close_15m: float
    high_15m: float
    low_15m: float
    volume_15m: float
    
    # 기술적 지표 (선택적 필드)
    # 5분봉 지표
    rsi_5m: Optional[float] = None    # 상대강도지수(RSI)
    atr_5m: Optional[float] = None    # 평균진폭(ATR)
    
    # 15분봉 지표
    rsi_15m: Optional[float] = None   # 상대강도지수(RSI)
    atr_15m: Optional[float] = None   # 평균진폭(ATR)


@dataclass
class MarketVO:
    """시장 데이터 컨테이너"""
    symbol: str
    current_price: float
    orderbook: Any
    candles_5m: List[Chart]
    candles_15m: List[Chart]
    indicator: Indicator


class DataCollector:
    """
    시장 데이터 수집 및 처리 클래스
    
    다양한 소스에서 시장 데이터를 수집하고 처리하는 기능 제공
    """
    
    def __init__(self, bybit_client: BybitClient):
        """
        DataCollector 초기화
        
        Args:
            bybit_client: Bybit API 클라이언트
        """
        self.bybit_client = bybit_client
        
        # 설정 로드
        config = ConfigLoader()
        self.settings = config.load_config("system_settings.json")
        self.candles_count = self.settings.get("candles_count", 200)  # 기본값 200
    
    def get_market_data(self, symbol: str) -> MarketVO:
        """
        특정 심볼에 대한 시장 데이터 수집
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            수집된 시장 데이터
        """
        # 현재 가격 조회
        ticker_info = self.bybit_client.get_current_price(symbol)
        current_price = None
        if ticker_info.get("retCode") == 0 and ticker_info.get("result", {}).get("list"):
            current_price = float(ticker_info["result"]["list"][0]["lastPrice"])
            print(f"현재 {symbol} 가격: {current_price}")
        
        # 오더북 조회
        orderbook = self.bybit_client.get_order_book(symbol)
        
        # 5분봉 데이터 조회
        kline_5m = self.bybit_client.get_kline_data(symbol, "5", self.candles_count)
        candles_5m = self._process_kline_data(kline_5m)
        print(f"5분봉 데이터 {len(candles_5m)}개 수집 완료")
        candles_5m_with_indicators = TechnicalIndicators.apply_indicators(candles_5m)
        print(f"5분봉 지표 계산 완료")
        
        # 15분봉 데이터 조회
        kline_15m = self.bybit_client.get_kline_data(symbol, "15", self.candles_count)
        candles_15m = self._process_kline_data(kline_15m)
        print(f"15분봉 데이터 {len(candles_15m)}개 수집 완료")
        candles_15m_with_indicators = TechnicalIndicators.apply_indicators(candles_15m)
        print(f"15분봉 지표 계산 완료")
        
        # 최신 지표 생성
        latest_5m = max(candles_5m_with_indicators, key=lambda x: x.timestamp)
        latest_15m = max(candles_15m_with_indicators, key=lambda x: x.timestamp)
        
        indicator = Indicator(
            # 5분봉 데이터
            timestamp_5m=latest_5m.timestamp,
            datetime_5m=latest_5m.datetime,
            open_5m=latest_5m.open,
            close_5m=latest_5m.close,
            high_5m=latest_5m.high,
            low_5m=latest_5m.low,
            volume_5m=latest_5m.volume,
            rsi_5m=latest_5m.rsi,
            atr_5m=latest_5m.atr,
            
            # 15분봉 데이터
            timestamp_15m=latest_15m.timestamp,
            datetime_15m=latest_15m.datetime,
            open_15m=latest_15m.open,
            close_15m=latest_15m.close,
            high_15m=latest_15m.high,
            low_15m=latest_15m.low,
            volume_15m=latest_15m.volume,
            rsi_15m=latest_15m.rsi,
            atr_15m=latest_15m.atr
        )
        
        return MarketVO(
            symbol=symbol,
            current_price=current_price,
            orderbook=orderbook.get("result", {}),
            candles_5m=candles_5m_with_indicators,
            candles_15m=candles_15m_with_indicators,
            indicator=indicator
        )
    
    def _process_kline_data(self, kline_data: Dict[str, Any]) -> List[Chart]:
        """
        Bybit API로부터 수신한 K-line 데이터 처리
        
        Args:
            kline_data: Bybit API 응답
            
        Returns:
            처리된 캔들 리스트
        """
        candles = []
        
        if kline_data.get("retCode") == 0 and kline_data.get("result", {}).get("list"):
            data_list = kline_data["result"]["list"]
            
            for candle_data in reversed(data_list):
                # Bybit API 응답 형식: [timestamp(ms), open, high, low, close, volume, turnover]
                if len(candle_data) >= 6:
                    timestamp = int(candle_data[0]) // 1000  # ms -> s 변환
                    
                    # UTC 형식의 날짜 문자열 생성
                    dt = time.gmtime(timestamp)
                    datetime_str = time.strftime('%Y-%m-%dT%H:%M:%SZ', dt)
                    
                    candle = Chart(
                        timestamp=timestamp,
                        datetime=datetime_str,  # UTC 시간 형식
                        open=float(candle_data[1]),
                        high=float(candle_data[2]),
                        low=float(candle_data[3]),
                        close=float(candle_data[4]),
                        volume=float(candle_data[5])
                    )
                    candles.append(candle)
            
            print(f"  처리된 캔들 수: {len(candles)}개")
        
        return candles
    
    def format_trading_summary(self, market_data: MarketVO) -> Dict[str, Any]:
        """
        트레이딩 요약 정보를 딕셔너리 형식으로 포맷팅
        
        Args:
            market_data: 시장 데이터
            
        Returns:
            포맷팅된 트레이딩 요약 정보
        """
        # 5분봉 데이터
        candles_5m = []
        for candle in market_data.candles_5m:
            candle_data = {
                "timestamp": candle.timestamp,
                "datetime": candle.datetime,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "rsi": candle.rsi,
                "atr": candle.atr
            }
            candles_5m.append(candle_data)
        
        # 15분봉 데이터
        candles_15m = []
        for candle in market_data.candles_15m:
            candle_data = {
                "timestamp": candle.timestamp,
                "datetime": candle.datetime,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "rsi": candle.rsi,
                "atr": candle.atr
            }
            candles_15m.append(candle_data)
        
        # 최신 데이터 가져오기
        latest_5m = market_data.candles_5m[-1]
        latest_15m = market_data.candles_15m[-1]
        
        # 현재 시간 정보
        current_datetime = latest_5m.datetime
        current_timestamp = latest_5m.timestamp
        
        # 트레이딩 요약 정보
        trading_summary = {
            "metadata": {
                "symbol": market_data.symbol,
                "current_time": current_datetime,
                "current_timestamp": current_timestamp,
                "current_price": market_data.current_price
            },
            "orderbook": market_data.orderbook,
            "indicators": {
                "current": {
                    "5m": {
                        "open": latest_5m.open,
                        "high": latest_5m.high,
                        "low": latest_5m.low,
                        "close": latest_5m.close,
                        "volume": latest_5m.volume,
                        "rsi": latest_5m.rsi,
                        "atr": latest_5m.atr
                    },
                    "15m": {
                        "open": latest_15m.open,
                        "high": latest_15m.high,
                        "low": latest_15m.low,
                        "close": latest_15m.close,
                        "volume": latest_15m.volume,
                        "rsi": latest_15m.rsi,
                        "atr": latest_15m.atr
                    }
                }
            },
            "historical_data": {
                "kline5m": candles_5m,
                "kline15m": candles_15m
            }
        }
        
        # RSI와 ATR 문자열 생성
        rsi_5m_str = "N/A" if latest_5m.rsi is None else f"{latest_5m.rsi:.2f}"
        atr_5m_str = "N/A" if latest_5m.atr is None else f"{latest_5m.atr:.2f}"
        rsi_15m_str = "N/A" if latest_15m.rsi is None else f"{latest_15m.rsi:.2f}"
        atr_15m_str = "N/A" if latest_15m.atr is None else f"{latest_15m.atr:.2f}"
        
        # Claude 형식으로 요약 정보 생성
        trading_summary["market_summary"] = f"""=== Trading Summary ===
5분봉 (Timestamp: {latest_5m.timestamp}, Datetime: {latest_5m.datetime})
 - Open: {latest_5m.open}, Close: {latest_5m.close}, High: {latest_5m.high}, Low: {latest_5m.low}, Volume: {latest_5m.volume:.2f}
 - RSI: {rsi_5m_str}, ATR: {atr_5m_str}

15분봉 (Timestamp: {latest_15m.timestamp}, Datetime: {latest_15m.datetime})
 - Open: {latest_15m.open}, Close: {latest_15m.close}, High: {latest_15m.high}, Low: {latest_15m.low}, Volume: {latest_15m.volume:.2f}
 - RSI: {rsi_15m_str}, ATR: {atr_15m_str}
"""
        
        return trading_summary
    
    def save_trading_summary(self, market_data: MarketVO, filepath: str) -> bool:
        """
        트레이딩 요약 정보를 JSON 파일로 저장
        
        Args:
            market_data: 시장 데이터
            filepath: 저장할 파일 경로
            
        Returns:
            저장 성공 여부
        """
        try:
            # 결과 디렉토리 생성
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # 트레이딩 요약 정보 포맷팅
            trading_summary = self.format_trading_summary(market_data)
            
            # JSON 파일로 저장 (NaN 값을 null로 처리)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(trading_summary, f, indent=2, default=lambda x: None if isinstance(x, (float, int)) and (math.isnan(x) or math.isinf(x)) else x)
            
            print(f"시장 데이터가 {filepath} 파일에 저장되었습니다.")
            return True
        except Exception as e:
            print(f"Error saving trading summary: {e}")
            return False


# 기본 사용 예시
if __name__ == "__main__":
    from config_loader import ConfigLoader
    import json
    
    # 설정 로드
    config = ConfigLoader()
    
    # 기본 설정 파일이 없으면 생성
    if not config.load_config("api_keys.json"):
        config.create_default_configs()
        print("기본 설정 파일이 생성되었습니다. config/api_keys.json 파일에 API 키를 입력하세요.")
        exit(1)
    
    api_keys = config.load_config("api_keys.json")
    
    if not api_keys.get("bybit_api", {}).get("key") or not api_keys.get("bybit_api", {}).get("secret"):
        print("API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
        exit(1)
    
    # 바이비트 클라이언트 생성
    client = BybitClient(
        api_keys["bybit_api"]["key"],
        api_keys["bybit_api"]["secret"]
    )
    
    # 데이터 수집기 생성
    collector = DataCollector(client)
    
    try:
        # BTC 시장 데이터 수집
        market_data = collector.get_market_data("BTCUSDT")
        
        # 출력
        print(f"심볼: {market_data.symbol}")
        print(f"현재 가격: {market_data.current_price}")
        print("\n5분봉 지표:")
        print(f"  시간: {market_data.indicator.datetime_5m}")
        print(f"  종가: {market_data.indicator.close_5m}")
        print(f"  RSI: {market_data.indicator.rsi_5m}")
        print(f"  ATR: {market_data.indicator.atr_5m}")
        
        print("\n15분봉 지표:")
        print(f"  시간: {market_data.indicator.datetime_15m}")
        print(f"  종가: {market_data.indicator.close_15m}")
        print(f"  RSI: {market_data.indicator.rsi_15m}")
        print(f"  ATR: {market_data.indicator.atr_15m}")
        
        # 캔들 개수 확인
        print(f"\n수집된 5분봉 캔들 수: {len(market_data.candles_5m)}")
        print(f"수집된 15분봉 캔들 수: {len(market_data.candles_15m)}")
        
        # 트레이딩 요약 정보 저장
        collector.save_trading_summary(market_data, "results/market_data_BTCUSDT.json")
        
    except Exception as e:
        print(f"오류 발생: {e}")