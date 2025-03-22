from typing import List, Dict, Any, Optional, Union
import pandas as pd
import numpy as np
import time
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Chart:
    """캔들스틱 차트 데이터 모델"""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    datetime: Optional[str] = None
    rsi: Optional[float] = None    # 상대강도지수(RSI)
    atr: Optional[float] = None    # 평균진폭(ATR)


class TechnicalIndicators:
    """
    기술적 지표를 계산하는 클래스
    
    ATR, OBV, RSI 지표를 계산하고 적용하는 기능 제공
    """
    
    @staticmethod
    def apply_indicators(candles: List[Chart]) -> List[Chart]:
        """
        캔들 리스트에 기술적 지표 적용
        
        Args:
            candles: 캔들 데이터 리스트
            
        Returns:
            기술적 지표가 적용된 캔들 리스트
        """
        # 데이터가 없으면 빈 리스트 반환
        if not candles:
            return []
        
        print(f"  기술적 지표 계산 시작 (캔들 {len(candles)}개)...")
        
        # 원본 데이터 보존을 위해 깊은 복사 수행
        candles_with_indicators = candles.copy()
        
        # pandas DataFrame으로 변환
        df = TechnicalIndicators._convert_to_dataframe(candles)
        
        # 지표 계산
        df = TechnicalIndicators._calculate_indicators(df)
        
        # 결과를 다시 Chart 객체로 변환
        result = []
        for i, row in df.iterrows():
            chart = Chart(
                timestamp=int(row['timestamp']),
                datetime=row['datetime'] if 'datetime' in row else time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(row['timestamp'])),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume']),
                rsi=float(row['rsi']) if not np.isnan(row['rsi']) else None,
                atr=float(row['atr']) if not np.isnan(row['atr']) else None
            )
            result.append(chart)
        
        print(f"  기술적 지표 계산 완료")
        return result
    
    @staticmethod
    def _convert_to_dataframe(candles: List[Chart]) -> pd.DataFrame:
        """
        캔들 리스트를 pandas DataFrame으로 변환
        
        Args:
            candles: 캔들 데이터 리스트
            
        Returns:
            pandas DataFrame
        """
        data = []
        for candle in candles:
            data.append({
                'timestamp': candle.timestamp,
                'datetime': candle.datetime,
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume
            })
        
        df = pd.DataFrame(data)
        
        # 타임스탬프로 정렬
        df = df.sort_values('timestamp')
        
        return df
    
    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        TA4J 기반의 자바 코드와 유사한 방식으로 기술적 지표 계산
        
        Args:
            df: 캔들 데이터가 포함된 DataFrame
            
        Returns:
            기술적 지표가 추가된 DataFrame
        """
        # 데이터가 충분하지 않으면 원본 반환
        min_periods = 14  # RSI 및 ATR에 필요한 최소 데이터 수
        if len(df) < min_periods:
            # NaN으로 채워진 열 추가
            for col in ['rsi', 'atr']:
                df[col] = np.nan
            return df
        
        # 1. RSI 14 (Wilder's RSI - TradingView 방식)
        delta = df['close'].diff()
        # 양수 변화량(상승)
        gain = delta.copy()
        gain[gain < 0] = 0
        # 음수 변화량(하락)의 절대값
        loss = -delta.copy()
        loss[loss < 0] = 0
        
        # RSI 계산을 위한 준비
        df['rsi'] = np.nan  # 모든 값을 NaN으로 초기화
        
        if len(df) < 14:
            return df  # 데이터가 부족하면 조기 반환
            
        # 첫 번째 평균 계산 (14일 단순 평균)
        first_avg_gain = gain.iloc[:14].mean()
        first_avg_loss = loss.iloc[:14].mean()
        
        # 첫 번째 RSI 계산
        if first_avg_loss != 0:
            rs = first_avg_gain / first_avg_loss
            df.loc[13, 'rsi'] = 100 - (100 / (1 + rs))
        else:
            df.loc[13, 'rsi'] = 100  # 하락이 없으면 RSI는 100
            
        # 나머지 기간에 대한 Wilder 스무딩 계산
        for i in range(14, len(df)):
            avg_gain = (first_avg_gain * 13 + gain.iloc[i]) / 14
            avg_loss = (first_avg_loss * 13 + loss.iloc[i]) / 14
            first_avg_gain = avg_gain  # 다음 계산을 위해 갱신
            first_avg_loss = avg_loss  # 다음 계산을 위해 갱신
            
            if avg_loss != 0:
                rs = avg_gain / avg_loss
                df.loc[i, 'rsi'] = 100 - (100 / (1 + rs))
            else:
                df.loc[i, 'rsi'] = 100  # 하락이 없으면 RSI는 100
        
        # 2. ATR (Average True Range) - TradingView 방식
        # True Range는 다음 중 최댓값:
        # 1. 현재 고가 - 현재 저가
        # 2. |현재 고가 - 이전 종가|
        # 3. |현재 저가 - 이전 종가|
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift(1))
        low_close = np.abs(df['low'] - df['close'].shift(1))
        
        # 첫 번째 값은 high-low만 사용
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        true_range.iloc[0] = high_low.iloc[0]  # 첫 번째 값은 단순 고가-저가 차이
        
        # ATR 계산 - Wilder의 스무딩 방식 (TradingView와 동일)
        df['atr'] = np.nan  # 모든 값을 NaN으로 초기화
        
        if len(df) < 14:
            return df  # 데이터가 부족하면 조기 반환
            
        # 초기 ATR 계산 (첫 14일 단순 평균)
        first_atr = true_range.iloc[:14].mean()
        df.loc[13, 'atr'] = first_atr
        
        # 이후 ATR 계산 (Wilder 점감 평균)
        for i in range(14, len(df)):
            df.loc[i, 'atr'] = (df.loc[i-1, 'atr'] * 13 + true_range.iloc[i]) / 14
        
        # OBV 계산 코드 제거
        
        return df


# 기본 사용 예시
if __name__ == "__main__":
    from bybit_client import BybitClient
    from config_loader import ConfigLoader
    
    # 설정 로드
    config = ConfigLoader()
    api_keys = config.load_config("api_keys.json")
    
    if not api_keys.get("bybit_api", {}).get("key") or not api_keys.get("bybit_api", {}).get("secret"):
        print("API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
    else:
        # 바이비트 클라이언트 생성
        client = BybitClient(
            api_keys["bybit_api"]["key"],
            api_keys["bybit_api"]["secret"]
        )
        
        try:
            # 캔들스틱 데이터 조회
            btc_kline = client.get_kline_data("BTCUSDT", "5", 100)
            
            if btc_kline.get("retCode") == 0:
                # 캔들 데이터 처리
                candles = []
                for candle_data in reversed(btc_kline.get("result", {}).get("list", [])):
                    # Bybit API 응답 형식: [timestamp(ms), open, high, low, close, volume, turnover]
                    candle = Chart(
                        timestamp=int(candle_data[0]) // 1000,  # ms -> s 변환
                        open=float(candle_data[1]),
                        high=float(candle_data[2]),
                        low=float(candle_data[3]),
                        close=float(candle_data[4]),
                        volume=float(candle_data[5])
                    )
                    candles.append(candle)
                
                # 지표 계산
                candles_with_indicators = TechnicalIndicators.apply_indicators(candles)
                
                # 지표 출력
                last_candle = candles_with_indicators[-1]
                print(f"마지막 캔들 시간: {last_candle.datetime}")
                print(f"가격: {last_candle.close}")
                print(f"RSI: {last_candle.rsi}")
                print(f"ATR: {last_candle.atr}")
                print(f"OBV: {last_candle.obv}")
            else:
                print(f"캔들 데이터 조회 실패: {btc_kline}")
        except Exception as e:
            print(f"오류 발생: {e}")