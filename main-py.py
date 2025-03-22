import os
import logging
import threading
import time
import signal
import argparse
import sys
from webhook_server import start_server
from decision_db_manager import DecisionDBManager
from decision_manager import DecisionManager
from config_loader import ConfigLoader
from bybit_client import BybitClient

# 데이터베이스 모듈 조건부 가져오기
try:
    from decision_db_manager import DecisionDBManager
    db_module_available = True
except ImportError:
    db_module_available = False

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/main.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("main")

# 전역 변수
running = True
webhook_thread = None
status_thread = None
decision_manager = None
db_manager = None

def start_webhook_server_thread():
    """웹훅 서버를 별도 스레드로 실행"""
    webhook_thread = threading.Thread(target=start_server)
    webhook_thread.daemon = True
    webhook_thread.start()
    logger.info("웹훅 서버 스레드 시작")
    return webhook_thread

def status_check_thread(interval=60):
    """
    주기적으로 상태를 체크하는 스레드
    
    Args:
        interval: 체크 간격 (초)
    """
    global running
    config = ConfigLoader()
    settings = config.load_config("system_settings.json")
    
    while running:
        try:
            logger.info("시스템 상태 체크 중...")
            
            # 모든 심볼에 대한 포지션 확인
            active_positions = []
            for symbol in settings.get("symbols", []):
                try:
                    position = decision_manager.get_active_position(symbol)
                    if position and position.get("exists", False):
                        logger.info(f"활성 포지션: {symbol} {position.get('position_type')} "
                                   f"크기: {position.get('size')} "
                                   f"진입가: {position.get('entry_price')} "
                                   f"손익: {position.get('unrealized_pnl')}")
                        active_positions.append(symbol)
                except Exception as e:
                    logger.error(f"{symbol} 포지션 확인 중 오류 발생: {e}")
            
            if not active_positions:
                logger.info("활성 포지션 없음")
            
            # 간격 대기
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)
        
        except Exception as e:
            logger.error(f"상태 체크 중 오류 발생: {e}")
            time.sleep(10)  # 오류 발생 시 10초 대기 후 재시도

def signal_handler(sig, frame):
    """
    시그널 핸들러 (Ctrl+C 등)
    """
    global running, db_manager
    logger.info("종료 신호 수신. 시스템을 종료합니다...")
    running = False
    
    # 데이터베이스 연결 정리
    if db_manager:
        logger.info("데이터베이스 연결 종료 중...")
        db_manager.close()
    
    sys.exit(0)

def initialize_environment():
    """
    환경 초기화 및 기본 설정 확인
    
    Returns:
        boolean: 초기화 성공 여부
    """
    global db_manager
    
    try:
        # 설정 로더 생성
        config = ConfigLoader()
        
        # 설정 파일 확인 및 생성
        api_keys = config.load_config("api_keys.json")
        if not api_keys:
            logger.info("API 키 설정 파일이 없습니다. 기본 설정 파일을 생성합니다.")
            config.create_default_configs()
            logger.info("config/api_keys.json 파일에 API 키를 입력한 후 다시 실행하세요.")
            return False
        
        # API 키 설정 확인 (BTC, ETH, SOL에 대한 각각의 API 키)
        api_keys_valid = True
        for coin in ["BTC", "ETH", "SOL"]:
            coin_api = api_keys.get("bybit_api", {}).get(coin, {})
            if not coin_api.get("key") or not coin_api.get("secret"):
                logger.error(f"{coin} Bybit API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
                api_keys_valid = False
        
        if not api_keys.get("claude_api", {}).get("key"):
            logger.error("Claude API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
            api_keys_valid = False
        
        if not api_keys.get("execution_server", {}).get("url"):
            logger.error("실행 서버 URL이 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
            api_keys_valid = False
        
        if not api_keys_valid:
            return False
        
        # 필요한 디렉토리 생성
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        
        # 설정 확인
        settings = config.load_config("system_settings.json")
        logger.info(f"웹훅 포트: {settings.get('webhook_port', 8000)}")
        logger.info(f"모니터링 대상 심볼: {', '.join(settings.get('symbols', []))}")
        logger.info(f"로그 레벨: {settings.get('log_level', 'INFO')}")
        
        # 데이터베이스 설정 확인 및 초기화
        if db_module_available:
            db_config = config.get_db_config()
            if db_config.get("enable_logging", True):
                try:
                    db_manager = DecisionDBManager(
                        db_config["host"],
                        db_config["user"],
                        db_config["password"],
                        db_config["database"]
                    )
                    logger.info("데이터베이스 연결 성공")
                except Exception as e:
                    logger.error(f"데이터베이스 초기화 실패: {e}")
                    logger.warning("데이터베이스 로깅 없이 계속합니다.")
        else:
            logger.warning("decision_db_manager 모듈을 찾을 수 없습니다. 데이터베이스 로깅 없이 계속합니다.")
        
        return True
    
    except Exception as e:
        logger.exception(f"환경 초기화 중 오류 발생: {e}")
        return False

def show_status():
    """시스템 상태 요약 출력"""
    try:
        config = ConfigLoader()
        settings = config.load_config("system_settings.json")
        execution_config = config.get_execution_server_config()
        db_config = config.get_db_config() if db_module_available else {}
        
        logger.info("=" * 60)
        logger.info("트레이딩뷰-클로드 결정 서버 시작")
        logger.info("=" * 60)
        logger.info(f"버전: 1.0.0")
        logger.info(f"웹훅 포트: {settings.get('webhook_port', 8000)}")
        logger.info(f"트레이딩 심볼: {', '.join(settings.get('symbols', []))}")
        logger.info(f"실행 서버 URL: {execution_config.get('url')}")
        logger.info(f"DB 로깅 활성화: {db_config.get('enable_logging', False)}")
        logger.info("=" * 60)
        logger.info("웹훅 엔드포인트: http://your-server-ip:8000/webhook")
        logger.info("시스템 상태 확인: http://your-server-ip:8000/health")
        logger.info("포지션 조회: http://your-server-ip:8000/positions")
        if db_module_available and db_config.get('enable_logging', False):
            logger.info("이벤트 로그 조회: http://your-server-ip:8000/events")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"상태 요약 출력 중 오류 발생: {e}")

def parse_arguments():
    """
    명령줄 인자 파싱
    
    Returns:
        argparse.Namespace: 파싱된 인자
    """
    parser = argparse.ArgumentParser(description='트레이딩뷰-클로드 결정 서버')
    parser.add_argument('--port', type=int, help='웹훅 서버 포트 지정')
    parser.add_argument('--init', action='store_true', help='기본 설정 파일 생성 후 종료')
    parser.add_argument('--init-db', action='store_true', help='데이터베이스 초기화 스크립트 생성')
    return parser.parse_args()

def create_db_init_script():
    """데이터베이스 초기화 스크립트 생성"""
    try:
        script_path = "db_init.sql"
        
        with open(script_path, 'w') as f:
            f.write("""-- 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS trading_decisions;
USE trading_decisions;

-- 이벤트 로그 테이블 (결정 서버 로깅용)
CREATE TABLE IF NOT EXISTS decision_events (
    eventId VARCHAR(36) PRIMARY KEY,
    eventName VARCHAR(50) NOT NULL COMMENT '이벤트 유형 (open_pos, close_pos, close_trend_pos)',
    eventSymbol VARCHAR(20) NOT NULL COMMENT '심볼 (BTCUSDT, ETHUSDT, SOLUSDT)',
    eventPos VARCHAR(10) COMMENT '신호 포지션 (long, short)',
    holdingPos VARCHAR(10) DEFAULT 'none' COMMENT '현재 보유 포지션 (none, long, short)',
    prAnswer VARCHAR(10) COMMENT 'Claude 응답 (yes, no)',
    prReason TEXT COMMENT 'Claude 응답 이유',
    sendExecuteServer TINYINT DEFAULT 0 COMMENT '실행 서버 전송 여부 (1=전송, 0=미전송)',
    occurKstDate DATETIME NOT NULL COMMENT '발생 시간 (한국 시간)',
    occurUtcDate DATETIME NOT NULL COMMENT '발생 시간 (UTC)',
    responseTime FLOAT COMMENT '응답 처리 시간 (초)',
    entryPrice FLOAT COMMENT '현재 포지션 진입 가격',
    currentPrice FLOAT COMMENT '현재 시장 가격',
    additionalInfo TEXT COMMENT '추가 정보 (JSON)',
    createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 생성 시간'
);

-- 인덱스 생성
CREATE INDEX idx_date_symbol ON decision_events(occurUtcDate, eventSymbol);
CREATE INDEX idx_event_name ON decision_events(eventName);
CREATE INDEX idx_symbol ON decision_events(eventSymbol);

-- 권한 설정 (필요시 주석 해제)
-- CREATE USER IF NOT EXISTS 'decision_user'@'localhost' IDENTIFIED BY 'decision_password';
-- GRANT ALL PRIVILEGES ON trading_decisions.* TO 'decision_user'@'localhost';
-- FLUSH PRIVILEGES;
""")
        
        logger.info(f"데이터베이스 초기화 스크립트가 {script_path}에 생성되었습니다.")
        logger.info("이 스크립트를 MySQL 서버에서 실행하여 데이터베이스를 초기화하세요.")
        logger.info("예: mysql -u root -p < db_init.sql")
        
    except Exception as e:
        logger.error(f"DB 초기화 스크립트 생성 중 오류 발생: {e}")

def main():
    """메인 실행 함수"""
    global running, webhook_thread, status_thread, decision_manager
    
    # 명령줄 인자 파싱
    args = parse_arguments()
    
    # 초기화 모드 처리
    if args.init:
        config = ConfigLoader()
        config.create_default_configs()
        logger.info("기본 설정 파일이 생성되었습니다. config/api_keys.json 및 config/system_settings.json 파일을 확인하세요.")
        return
    
    # DB 초기화 스크립트 생성 모드 처리
    if args.init_db:
        create_db_init_script()
        return
    
    # 환경 초기화
    if not initialize_environment():
        logger.error("환경 초기화에 실패했습니다. 프로그램을 종료합니다.")
        return
    
    # 포트 설정
    if args.port:
        config = ConfigLoader()
        settings = config.load_config("system_settings.json")
        settings["webhook_port"] = args.port
        config.save_config("system_settings.json", settings)
        logger.info(f"웹훅 서버 포트가 {args.port}로 설정되었습니다.")
    
    # 결정 매니저 초기화
    decision_manager = DecisionManager()
    
    # 시스템 상태 요약 출력
    show_status()
    
    # 시그널 핸들러 설정
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 웹훅 서버 스레드 시작
        webhook_thread = start_webhook_server_thread()
        
        # 상태 체크 스레드 시작
        status_thread = threading.Thread(target=status_check_thread)
        status_thread.daemon = True
        status_thread.start()
        logger.info("상태 체크 스레드 시작")
        
        # 메인 스레드 유지
        while running:
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("사용자에 의한 프로그램 종료")
    
    except Exception as e:
        logger.exception(f"실행 중 오류 발생: {e}")
    
    finally:
        running = False
        
        # 데이터베이스 연결 정리
        if db_manager:
            logger.info("데이터베이스 연결 종료 중...")
            db_manager.close()
            
        logger.info("프로그램 종료")

if __name__ == "__main__":
    main()