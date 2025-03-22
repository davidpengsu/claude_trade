# 트레이딩뷰 웹훅과 Claude 3.7 Sonnet 결정 서버

이 프로젝트는 트레이딩뷰의 파인스크립트에서 생성된 기술적 신호와 Claude 3.7 Sonnet AI를 결합하여 암호화폐 트레이딩 결정을 최적화하는 시스템의 **결정 서버** 부분을 구현합니다.

## 시스템 아키텍처

전체 시스템은 두 가지 주요 컴포넌트로 구성됩니다:

1. **결정 서버** (이 프로젝트): 
   - 트레이딩뷰 웹훅을 수신하고 처리
   - Claude AI를 통해 거래 결정 검증
   - 포지션 확인 (실행하지 않음)
   - 결정 신호를 실행 서버로 전달

2. **실행 서버** (별도 프로젝트):
   - 결정 서버에서 검증된 신호를 수신
   - 실제 거래 실행
   - 포지션 관리 (TP/SL 설정 등)

## 코인별 API 키 구조

이 시스템은 코인별로 별도의 Bybit API 키를 사용합니다:
- BTC 전용 API 키
- ETH 전용 API 키
- SOL 전용 API 키

Claude AI는 하나의 API 키를 공유하여 사용합니다.

## 주요 기능

- **웹훅 엔드포인트**: 트레이딩뷰에서 발생한 기술적 신호를 수신
- **포지션 확인**: 각 코인별 API 키를 사용하여 현재 활성 포지션 확인
- **AI 검증**: Claude 3.7 Sonnet을 통해 거래 결정 검증
- **신호 전달**: 검증된 결정을 실행 서버로 전달

## 요청 형식

트레이딩뷰에서 보내는 웹훅 포맷:

1. **포지션 진입 신호**:
```json
{
  "event": "open_pos",
  "symbol": "BTCUSDT",
  "position": "Long"
}
```

2. **포지션 청산 신호**:
```json
{
  "event": "close_pos",
  "symbol": "BTCUSDT"
}
```

3. **추세선 터치 신호**:
```json
{
  "event": "close_trend_pos",
  "symbol": "BTCUSDT"
}
```

## 설치 및 실행

### 필수 요구사항

- Python 3.8 이상
- 필요한 패키지 설치:
```
pip install -r requirements.txt
```

### 설정 파일

1. 초기 설정 파일 생성:
```
python main.py --init
```

2. `config/api_keys.json` 파일에 API 키 정보 입력:
```json
{
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
```

3. `config/system_settings.json` 파일에서 설정 조정

### 실행 방법

```
python main.py
```

특정 포트로 실행:
```
python main.py --port 9000
```

## API 엔드포인트

- 웹훅 수신: `POST /webhook`
- 서버 상태 확인: `GET /health`
- 현재 포지션 조회: `GET /positions`

## 코드 구조

- `main.py`: 메인 애플리케이션 진입점
- `config_loader.py`: 설정 파일 로딩 유틸리티
- `webhook_server.py`: 웹훅 수신 및 처리
- `decision_manager.py`: 거래 결정 관리
- `bybit_client.py`: Bybit API 클라이언트
- `claude_client.py`: Claude AI API 클라이언트
- `data_collector.py`: 시장 데이터 수집
- `technical_indicators.py`: 기술적 지표 계산
- `execution_client.py`: 실행 서버 클라이언트

## 로깅

- 모든 로그는 `logs` 디렉토리에 저장됩니다
- 각 컴포넌트별로 별도의 로그 파일이 생성됩니다

## 다음 단계: 실행 서버 개발

결정 서버에서 전송한 신호를 수신하고 실제 거래를 실행하는 '실행 서버'를 개발해야 합니다.
실행 서버는 다음과 같은 기능을 포함해야 합니다:

- 결정 서버로부터 신호 수신
- 실제 거래 실행
- 포지션 관리 (TP/SL 설정 등)
- 거래 결과 기록 및 분석
