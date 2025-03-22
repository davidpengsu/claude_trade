import json
import logging
import os
import time
import traceback
from flask import Flask, request, jsonify
from decision_manager import DecisionManager
from config_loader import ConfigLoader
from threading import Lock

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
            
            # 요청 처리 전 기존 요청이 처리 중인지 확인 (중복 요청 방지)
            request_id = f"{event}_{symbol}_{int(time.time())}"
            
            # 이벤트 타입에 따른 처리
            if event == 'open_pos':
                position = data.get('position')  # 'position'이 아닌 'position'으로 표기됨에 주의
                if not position:
                    logger.error("open_pos 이벤트에 position 필드 누락")
                    return jsonify({"status": "error", "message": "Missing position field"}), 400
                
                # 포지션 진입 처리
                result = decision_manager.handle_open_position(symbol, position)
                logger.info(f"포지션 진입 결정 결과: {result}")
                return jsonify(result)
            
            elif event == 'close_pos':
                # 포지션 청산 처리
                result = decision_manager.handle_close_position(symbol)
                logger.info(f"포지션 청산 결정 결과: {result}")
                return jsonify(result)
            
            elif event == 'close_trend_pos':
                # 추세선 터치로 인한 포지션 검증
                result = decision_manager.handle_trend_touch(symbol)
                logger.info(f"추세선 터치 결정 결과: {result}")
                return jsonify(result)
            
            else:
                logger.warning(f"알 수 없는 이벤트 타입: {event}")
                return jsonify({"status": "error", "message": f"Unknown event type: {event}"}), 400
        
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"웹훅 처리 중 오류 발생: {e}\n{error_trace}")
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
            "active_symbols": []
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

# 서버 시작 시간 기록
start_time = time.time()

def start_server():
    """웹훅 서버 시작"""
    port = settings.get("webhook_port", 8000)
    logger.info(f"웹훅 서버 시작 (포트: {port})")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

if __name__ == '__main__':
    start_server()