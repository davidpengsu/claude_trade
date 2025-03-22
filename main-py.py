import os
import logging
import threading
import time
import signal
import argparse
import sys
from webhook_server import start_server
from position_manager import PositionManager
from config_loader import ConfigLoader
from bybit_client import BybitClient

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
position_manager = None

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
    api_keys = config.load_config("api_keys.json")
    settings = config.load_config("system_settings.json")
    
    bybit_client = BybitClient(
        api_keys["bybit_api"]["key"],
        api_keys["bybit_api"]["secret"]
    )
    
    while running:
        try:
            logger.info("시스템 상태 체크 중...")
            
            # 계좌 잔고 확인
            try:
                balance = bybit_client.get_account_balance()
                logger.info(f"현재 계좌 잔고: {balance['total']} USDT (가용: {balance['available']} USDT)")
            except Exception as e:
                logger.error(f"계좌 잔고 확인 중 오류 발생: {e}")
            
            # 모든 심볼에 대한 포지션 확인
            active_positions = []
            for symbol in settings.get("symbols", []):
                try:
                    position = bybit_client.get_positions(symbol)
                    if position.get("exists", False):
                        logger.info(f"활성 포지션: {symbol} {position.get('position_type')} "
                                   f"크기: {position.get('size')} "
                                   f"진입가: {position.get('entry_price')} "
                                   f"손익: {position.get('unrealized_pnl')}")
                        active_positions.append(symbol)
                except Exception as e:
                    logger.error(f"{symbol} 포지션 확인 중 오류 발생: {e}")
            
            if not active_positions:
                logger.info("활성 포지션 없음")
            
            # 시스템 설정값 출력
            position_size_mode = settings.get("position_size_mode", "percent")
            position_size_text = f"{settings.get('position_size_fixed', 100)} USDT" if position_size_mode == "fixed" else f"{settings.get('position_size_percent', 10)}%"
            
            logger.info(f"시스템 설정: "
                       f"포지션 크기={position_size_text}, "
                       f"레버리지={settings.get('leverage', 5)}x, "
                       f"SL={settings.get('sl_percent', 1.5)}%, "
                       f"TP={settings.get('tp_percent', 3.0)}%")
            
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
    global running
    logger.info("종료 신호 수신. 시스템을 종료합니다...")
    running = False
    sys.exit(0)

def initialize_environment():
    """
    환경 초기화 및 기본 설정 확인
    
    Returns:
        boolean: 초기화 성공 여부
    """
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
        
        # API 키 설정 확인
        if not api_keys.get("bybit_api", {}).get("key") or not api_keys.get("bybit_api", {}).get("secret"):
            logger.error("Bybit API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
            return False
        
        if not api_keys.get("claude_api", {}).get("key"):
            logger.error("Claude API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
            return False
        
        # 필요한 디렉토리 생성
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        
        # 설정 확인
        settings = config.load_config("system_settings.json")
        logger.info(f"웹훅 포트: {settings.get('webhook_port', 8000)}")
        logger.info(f"모니터링 대상 심볼: {', '.join(settings.get('symbols', []))}")
        logger.info(f"로그 레벨: {settings.get('log_level', 'INFO')}")
        logger.info(f"테스트 모드: {'활성화' if settings.get('test_mode', False) else '비활성화'}")
        
        return True
    
    except Exception as e:
        logger.exception(f"환경 초기화 중 오류 발생: {e}")
        return False

def show_status():
    """시스템 상태 요약 출력"""
    try:
        config = ConfigLoader()
        settings = config.load_config("system_settings.json")
        
        # 포지션 사이즈 설정 확인
        position_size_mode = settings.get("position_size_mode", "percent")
        position_size_text = f"{settings.get('position_size_fixed', 100)} USDT" if position_size_mode == "fixed" else f"{settings.get('position_size_percent', 10)}%"
        
        logger.info("=" * 60)
        logger.info("트레이딩뷰-클로드 트레이딩 시스템 시작")
        logger.info("=" * 60)
        logger.info(f"버전: 1.0.0")
        logger.info(f"웹훅 포트: {settings.get('webhook_port', 8000)}")
        logger.info(f"트레이딩 심볼: {', '.join(settings.get('symbols', []))}")
        logger.info(f"포지션 크기: {position_size_text}")
        logger.info(f"레버리지: {settings.get('leverage', 5)}x")
        logger.info(f"손절 비율: {settings.get('sl_percent', 1.5)}%")
        logger.info(f"익절 비율: {settings.get('tp_percent', 3.0)}%")
        if settings.get("test_mode", False):
            logger.info("⚠️ 테스트 모드로 실행 중입니다 ⚠️")
        logger.info("=" * 60)
        logger.info("웹훅 엔드포인트: http://your-server-ip:8000/webhook")
        logger.info("시스템 상태 확인: http://your-server-ip:8000/health")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"상태 요약 출력 중 오류 발생: {e}")

def parse_arguments():
    """
    명령줄 인자 파싱
    
    Returns:
        argparse.Namespace: 파싱된 인자
    """
    parser = argparse.ArgumentParser(description='트레이딩뷰-클로드 트레이딩 시스템')
    parser.add_argument('--test', action='store_true', help='테스트 모드로 실행 (실제 거래 없음)')
    parser.add_argument('--port', type=int, help='웹훅 서버 포트 지정')
    parser.add_argument('--init', action='store_true', help='기본 설정 파일 생성 후 종료')
    return parser.parse_args()

def main():
    """메인 실행 함수"""
    global running, webhook_thread, status_thread, position_manager
    
    # 명령줄 인자 파싱
    args = parse_arguments()
    
    # 초기화 모드 처리
    if args.init:
        config = ConfigLoader()
        config.create_default_configs()
        logger.info("기본 설정 파일이 생성되었습니다. config/api_keys.json 및 config/system_settings.json 파일을 확인하세요.")
        return
    
    # 환경 초기화
    if not initialize_environment():
        logger.error("환경 초기화에 실패했습니다. 프로그램을 종료합니다.")
        return
    
    # 테스트 모드 설정
    if args.test:
        config = ConfigLoader()
        settings = config.load_config("system_settings.json")
        settings["test_mode"] = True
        config.save_config("system_settings.json", settings)
        logger.info("⚠️ 테스트 모드로 설정되었습니다 ⚠️")
    
    # 포트 설정
    if args.port:
        config = ConfigLoader()
        settings = config.load_config("system_settings.json")
        settings["webhook_port"] = args.port
        config.save_config("system_settings.json", settings)
        logger.info(f"웹훅 서버 포트가 {args.port}로 설정되었습니다.")
    
    # 포지션 매니저 초기화
    position_manager = PositionManager()
    
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
        logger.info("프로그램 종료")

if __name__ == "__main__":
    main()