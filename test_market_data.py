import os
import json
import math
from typing import Dict, Any

from config_loader import ConfigLoader
from bybit_client import BybitClient
from technical_indicators import TechnicalIndicators, Chart
from data_collector import DataCollector, MarketVO


def setup_environment():
    """환경 설정 및 필요한 디렉토리 생성"""
    # 설정 로더 생성
    config = ConfigLoader()
    
    # 기본 설정 파일이 없으면 생성
    if not config.load_config("api_keys.json"):
        config.create_default_configs()
        print("기본 설정 파일이 생성되었습니다.")
        print("config/api_keys.json 파일에 API 키를 입력한 후 다시 실행하세요.")
        return None
    
    # API 키 설정 확인
    api_keys = config.load_config("api_keys.json")
    if not api_keys.get("bybit_api", {}).get("key") or not api_keys.get("bybit_api", {}).get("secret"):
        print("API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
        return None
    
    return api_keys


def test_bybit_client(api_keys: Dict[str, Any]):
    """바이비트 클라이언트 테스트"""
    print("\n===== 바이비트 클라이언트 테스트 =====")
    
    client = BybitClient(
        api_keys["bybit_api"]["key"], 
        api_keys["bybit_api"]["secret"]
    )
    
    try:
        # 현재 가격 조회
        ticker = client.get_current_price("BTCUSDT")
        if ticker.get("retCode") == 0:
            price = ticker["result"]["list"][0]["lastPrice"]
            print(f"BTC 현재 가격: {price}")
        else:
            print(f"가격 조회 실패: {ticker}")
        
        # 설정에서 캔들 개수 가져오기
        config = ConfigLoader()
        settings = config.load_config("system_settings.json")
        candles_count = settings.get("candles_count", 200)
        
        # 캔들스틱 데이터 조회 (테스트용으로 10개만)
        kline = client.get_kline_data("BTCUSDT", "5", 10)
        if kline.get("retCode") == 0:
            candles = kline["result"]["list"]
            print(f"5분봉 캔들 {len(candles)}개 조회 성공 (전체 설정: {candles_count}개)")
        else:
            print(f"캔들 데이터 조회 실패: {kline}")
        
        return client
    
    except Exception as e:
        print(f"바이비트 클라이언트 테스트 중 오류 발생: {e}")
        return None


def test_technical_indicators(client: BybitClient):
    """기술적 지표 계산 테스트"""
    print("\n===== 기술적 지표 계산 테스트 =====")
    
    try:
        # 캔들스틱 데이터 조회
        kline = client.get_kline_data("BTCUSDT", "5", 50)
        
        if kline.get("retCode") == 0:
            # 캔들 데이터 처리
            candles = []
            for candle_data in reversed(kline["result"]["list"]):
                candle = Chart(
                    timestamp=int(candle_data[0]) // 1000,  # ms -> s 변환
                    open=float(candle_data[1]),
                    high=float(candle_data[2]),
                    low=float(candle_data[3]),
                    close=float(candle_data[4]),
                    volume=float(candle_data[5])
                )
                candles.append(candle)
            
            print(f"캔들 {len(candles)}개 처리 완료")
            
            # 지표 계산
            candles_with_indicators = TechnicalIndicators.apply_indicators(candles)
            
            # 결과 출력
            last_candle = candles_with_indicators[-1]
            print("\n최신 캔들 지표:")
            print(f"  종가: {last_candle.close}")
            print(f"  RSI: {last_candle.rsi}")
            print(f"  ATR: {last_candle.atr}")
            
            return True
        else:
            print(f"캔들 데이터 조회 실패: {kline}")
            return False
    
    except Exception as e:
        print(f"기술적 지표 계산 테스트 중 오류 발생: {e}")
        return False


def test_data_collector(client: BybitClient):
    """데이터 수집기 테스트"""
    print("\n===== 데이터 수집기 테스트 =====")
    
    try:
        # 데이터 수집기 생성
        collector = DataCollector(client)
        
        # 시장 데이터 수집
        market_data = collector.get_market_data("BTCUSDT")
        
        # 결과 출력
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
        
        # 수집한 시장 데이터를 JSON으로 저장
        save_market_data(market_data)
        
        return market_data
    
    except Exception as e:
        print(f"데이터 수집기 테스트 중 오류 발생: {e}")
        return None


def save_market_data(market_data: MarketVO):
    """수집한 시장 데이터를 JSON 파일로 저장"""
    # 결과 디렉토리 생성
    if not os.path.exists("results"):
        os.makedirs("results")
    
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
    
    # 데이터 저장을 위한 사전 생성
    data = {
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
    
    # 요약 정보 추가
    data["market_summary"] = f"""=== Trading Summary ===
5분봉 (Timestamp: {latest_5m.timestamp}, Datetime: {latest_5m.datetime})
 - Open: {latest_5m.open}, Close: {latest_5m.close}, High: {latest_5m.high}, Low: {latest_5m.low}, Volume: {latest_5m.volume:.2f}
 - RSI: {rsi_5m_str}, ATR: {atr_5m_str}

15분봉 (Timestamp: {latest_15m.timestamp}, Datetime: {latest_15m.datetime})
 - Open: {latest_15m.open}, Close: {latest_15m.close}, High: {latest_15m.high}, Low: {latest_15m.low}, Volume: {latest_15m.volume:.2f}
 - RSI: {rsi_15m_str}, ATR: {atr_15m_str}
"""
    
    # JSON 파일로 저장 (NaN 값을 null로 처리)
    filepath = f"results/market_data_{market_data.symbol}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=lambda x: None if isinstance(x, (float, int)) and (math.isnan(x) or math.isinf(x)) else x)
    
    print(f"\n시장 데이터가 {filepath} 파일에 저장되었습니다.")


def main():
    """메인 테스트 함수"""
    print("===== 시장 데이터 수집 및 기술적 지표 계산 테스트 =====")
    
    # 환경 설정
    api_keys = setup_environment()
    if not api_keys:
        return
    
    # 바이비트 클라이언트 테스트
    client = test_bybit_client(api_keys)
    if not client:
        return
    
    # 기술적 지표 계산 테스트
    if not test_technical_indicators(client):
        return
    
    # 데이터 수집기 테스트
    market_data = test_data_collector(client)
    if not market_data:
        return
    
    print("\n===== 모든 테스트가 성공적으로 완료되었습니다 =====")


if __name__ == "__main__":
    main()