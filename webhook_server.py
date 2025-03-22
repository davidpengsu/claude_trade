import json
import logging
import os
import time
import traceback
from flask import Flask, request, jsonify
from threading import Lock
from datetime import datetime, timedelta  # 확인: timedelta 추가됨
from decision_db_manager import DecisionDBManager
from decision_manager import DecisionManager
from config_loader import ConfigLoader

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/webhook.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("webhook_server")

# Flask 앱 생성
app = Flask(__name__)

# 설정 로드
config = ConfigLoader()
settings = config.load_config("system_settings.json")
db_config = config.get_db_config()

# 데이터베이스 로깅 사용 여부
enable_db_logging = db_config.get('enable_logging', True)

# 데이터베이스 매니저 초기화 (로깅 활성화 시)
db_manager = None
if enable_db_logging:
    try:
        db_manager = DecisionDBManager(
            db_config['host'],
            db_config['user'],
            db_config['password'],
            db_config['database']
        )
        logger.info("데이터베이스 로깅 활성화됨")
    except Exception as e:
        logger.error(f"데이터베이스 매니저 초기화 실패: {e}")
        enable_db_logging = False

# 결정 매니저 인스턴스 생성
decision_manager = DecisionManager()

# 요청 처리 중 동시성 이슈 방지를 위한 락
request_lock = Lock()

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    트레이딩뷰 웹훅 엔드포인트
    
    JSON 형식:
    1. 포지션 진입: {"event": "open_pos", "symbol": "SOLUSDT", "position": "Long"}
    2. 포지션 청산: {"event": "close_pos", "symbol": "SOLUSDT"}
    3. 추세선 터치: {"event": "close_trend_pos", "symbol": "SOLUSDT"}
    """
    with request_lock:  # 락을 사용하여 동시 요청 처리 방지
        start_time = time.time()
        event_id = str(int(time.time())) + "-" + str(hash(str(request.data)))[:8]
        event_data = {}
        
        try:
            # 요청 데이터 파싱
            if not request.is_json:
                logger.error("JSON 형식이 아닌 요청 수신")
                return jsonify({"status": "error", "message": "JSON 형식으로 요청해주세요"}), 400
            
            data = request.json
            logger.info(f"웹훅 수신: {data}")
            
            # 데이터 유효성 검사
            if not data or not isinstance(data, dict):
                logger.error("유효하지 않은 웹훅 데이터")
                return jsonify({"status": "error", "message": "Invalid webhook data"}), 400
            
            # 이벤트 처리
            event = data.get('event')
            symbol = data.get('symbol')
            
            if not event or not symbol:
                logger.error("필수 필드 누락: event 또는 symbol")
                return jsonify({"status": "error", "message": "Missing required fields: event or symbol"}), 400
            
            # 심볼을 대문자로 변환 (예: solusdt -> SOLUSDT)
            symbol = symbol.upper()
            
            # 이벤트 기본 정보 생성
            utc_now = datetime.utcnow().replace(microsecond=0)
            kst_now = utc_now + timedelta(hours=9)  # KST(UTC+9) 시간 계산
            
            event_data = {
                'eventId': event_id,
                'eventName': event,
                'eventSymbol': symbol,
                'occurKstDate': kst_now,
                'occurUtcDate': utc_now
            }
            
            # 현재 포지션 확인
            current_position = decision_manager.get_active_position(symbol)
            event_data['holdingPos'] = current_position.get('position_type', 'none') if current_position else 'none'
            
            # 현재 가격 확인
            try:
                current_price = decision_manager.get_bybit_client(symbol).get_current_price(symbol)
                event_data['currentPrice'] = current_price
                
                if current_position:
                    event_data['entryPrice'] = current_position.get('entry_price')
            except Exception as e:
                logger.warning(f"현재 가격 조회 실패: {e}")
            
            # 이벤트 타입에 따른 처리
            if event == 'open_pos':
                position = data.get('position')  # 포지션 필드
                if not position:
                    logger.error("open_pos 이벤트에 position 필드 누락")
                    
                    # 에러 정보 로깅
                    if enable_db_logging:
                        event_data['additionalInfo'] = json.dumps({
                            "error": "Missing position field",
                            "raw_data": data
                        })
                        db_manager.log_event(event_data)
                    
                    return jsonify({"status": "error", "message": "Missing position field"}), 400
                
                # 이벤트 데이터 업데이트
                event_data['eventPos'] = position.lower()
                
                # 포지션 진입 처리
                result = decision_manager.handle_open_position(symbol, position)
                logger.info(f"포지션 진입 결정 결과: {result}")
                
                # 결과 정보 업데이트
                if 'ai_decision' in result:
                    event_data['prAnswer'] = result['ai_decision'].get('Answer')
                    event_data['prReason'] = result['ai_decision'].get('Reason')
                
                event_data['sendExecuteServer'] = 1 if result.get('status') == 'success' else 0
                event_data['responseTime'] = time.time() - start_time
                
                # 추가 정보
                event_data['additionalInfo'] = json.dumps({
                    "decision_result": result,
                    "raw_request": data
                })
                
                # 이벤트 로깅
                if enable_db_logging:
                    db_manager.log_event(event_data)
                
                return jsonify(result)
            
            elif event == 'close_pos':
                # 포지션 청산 처리
                result = decision_manager.handle_close_position(symbol)
                logger.info(f"포지션 청산 결정 결과: {result}")
                
                # 결과 정보 업데이트
                if 'ai_decision' in result:
                    event_data['prAnswer'] = result['ai_decision'].get('Answer')
                    event_data['prReason'] = result['ai_decision'].get('Reason')
                
                event_data['sendExecuteServer'] = 1 if result.get('status') == 'success' else 0
                event_data['responseTime'] = time.time() - start_time
                
                # 추가 정보
                event_data['additionalInfo'] = json.dumps({
                    "decision_result": result,
                    "raw_request": data
                })
                
                # 이벤트 로깅
                if enable_db_logging:
                    db_manager.log_event(event_data)
                
                return jsonify(result)
            
            elif event == 'close_trend_pos':
                # 추세선 터치로 인한 포지션 검증
                result = decision_manager.handle_trend_touch(symbol)
                logger.info(f"추세선 터치 결정 결과: {result}")
                
                # 결과 정보 업데이트
                if 'ai_decision' in result:
                    event_data['prAnswer'] = result['ai_decision'].get('Answer')
                    event_data['prReason'] = result['ai_decision'].get('Reason')
                
                event_data['sendExecuteServer'] = 1 if result.get('status') == 'success' else 0
                event_data['responseTime'] = time.time() - start_time
                
                # 추가 정보
                event_data['additionalInfo'] = json.dumps({
                    "decision_result": result,
                    "raw_request": data
                })
                
                # 이벤트 로깅
                if enable_db_logging:
                    db_manager.log_event(event_data)
                
                return jsonify(result)
            
            else:
                logger.warning(f"알 수 없는 이벤트 타입: {event}")
                
                # 에러 정보 로깅
                if enable_db_logging:
                    event_data['additionalInfo'] = json.dumps({
                        "error": f"Unknown event type: {event}",
                        "raw_data": data
                    })
                    db_manager.log_event(event_data)
                
                return jsonify({"status": "error", "message": f"Unknown event type: {event}"}), 400
        
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"웹훅 처리 중 오류 발생: {e}\n{error_trace}")
            
            # 에러 정보 로깅
            if enable_db_logging and event_data:
                event_data['additionalInfo'] = json.dumps({
                    "error": str(e),
                    "traceback": error_trace
                })
                event_data['responseTime'] = time.time() - start_time
                db_manager.log_event(event_data)
            
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            # 처리 시간 로깅
            processing_time = time.time() - start_time
            logger.info(f"웹훅 처리 완료 (소요 시간: {processing_time:.3f}초)")

@app.route('/health', methods=['GET'])
def health_check():
    """
    서버 상태 확인 엔드포인트
    """
    try:
        # 기본 상태 정보
        health_info = {
            "status": "OK",
            "timestamp": int(time.time()),
            "uptime": int(time.time() - start_time),
            "active_symbols": [],
            "db_logging": enable_db_logging
        }
        
        # 활성 포지션 정보 수집
        for symbol in settings.get("symbols", []):
            position = decision_manager.get_active_position(symbol)
            if position and position.get("exists", False):
                health_info["active_symbols"].append({
                    "symbol": symbol,
                    "position_type": position.get("position_type"),
                    "entry_price": position.get("entry_price"),
                    "current_pnl": position.get("unrealized_pnl")
                })
        
        return jsonify(health_info)
    except Exception as e:
        logger.error(f"상태 확인 중 오류 발생: {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """
    현재 활성 포지션 정보 조회 엔드포인트
    """
    try:
        positions = {}
        
        # 모든 심볼에 대해 포지션 정보 수집
        for symbol in settings.get("symbols", []):
            position = decision_manager.get_active_position(symbol)
            if position and position.get("exists", False):
                positions[symbol] = {
                    "position_type": position.get("position_type"),
                    "entry_price": position.get("entry_price"),
                    "size": position.get("size"),
                    "leverage": position.get("leverage"),
                    "unrealized_pnl": position.get("unrealized_pnl")
                }
        
        return jsonify({
            "status": "success",
            "positions": positions,
            "count": len(positions)
        })
    except Exception as e:
        logger.error(f"포지션 정보 조회 중 오류 발생: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/events', methods=['GET'])
def get_events():
    """
    이벤트 로그 조회 엔드포인트
    """
    if not enable_db_logging:
        return jsonify({"status": "error", "message": "데이터베이스 로깅이 비활성화되어 있습니다"}), 400
    
    try:
        symbol = request.args.get('symbol')
        limit = int(request.args.get('limit', 100))
        
        if symbol:
            events = db_manager.get_events_by_symbol(symbol, limit)
        else:
            events = db_manager.get_recent_events(limit)
        
        return jsonify({
            "status": "success",
            "events": events,
            "count": len(events)
        })
    except Exception as e:
        logger.error(f"이벤트 로그 조회 중 오류 발생: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# 서버 시작 시간 기록
start_time = time.time()

def start_server():
    """웹훅 서버 시작"""
    port = settings.get("webhook_port", 8000)
    logger.info(f"웹훅 서버 시작 (포트: {port})")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

# 서버 종료 시 DB 연결 정리
import atexit

def shutdown():
    global db_manager
    if db_manager:
        logger.info("서버 종료: 데이터베이스 연결 종료")
        db_manager.close()

atexit.register(shutdown)

if __name__ == '__main__':
    start_server()