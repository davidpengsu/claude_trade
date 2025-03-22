import pymysql
import logging
import os
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/decision_db.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("decision_db_manager")

class DecisionDBManager:
    """
    결정 서버 데이터베이스 관리 클래스
    
    웹훅 이벤트 및 결정 프로세스 로그를 저장하고 조회하는 기능 제공
    """
    
    def __init__(self, host: str, user: str, password: str, database: str = "trading_decisions", port: int = 3306):
        """
        DecisionDBManager 초기화
        
        Args:
            host: 데이터베이스 호스트
            user: 데이터베이스 사용자
            password: 데이터베이스 비밀번호
            database: 데이터베이스 이름
            port: MySQL 포트
        """
        self.config = {
            'host': host,
            'user': user,
            'password': password,
            'database': database,
            'port': port,
            'charset': 'utf8mb4',
            'connect_timeout': 10,  # 연결 타임아웃 설정
            'cursorclass': pymysql.cursors.DictCursor
        }
        self._init_connection()
    
    def _init_connection(self):
        """데이터베이스 연결 초기화"""
        try:
            self.conn = pymysql.connect(**self.config)
            logger.info("데이터베이스 연결 성공")
        except pymysql.Error as err:
            logger.error(f"데이터베이스 연결 실패: {err}")
            raise
    
    def _ensure_connection(self):
        """연결 유효성 확인 및 재연결"""
        try:
            # PyMySQL에서는 is_connected가 없으므로 간단한 쿼리로 연결 상태 확인
            self.conn.ping(reconnect=True)
        except pymysql.Error as e:
            logger.error(f"데이터베이스 재연결 중 오류 발생: {e}")
            self._init_connection()
    
    def log_event(self, event_data: Dict[str, Any]) -> str:
        """
        결정 이벤트 로그 저장
        
        Args:
            event_data: 이벤트 데이터
            
        Returns:
            생성된 이벤트 ID
        """
        self._ensure_connection()
        
        # 이벤트 ID 생성
        event_id = event_data.get('eventId', str(uuid.uuid4()))
        
        # 한국 시간 (KST, UTC+9) 계산
        utc_now = datetime.utcnow()
        kst_now = utc_now + timedelta(hours=9)
        
        # 기본값 설정
        event_data.setdefault('eventId', event_id)
        event_data.setdefault('occurKstDate', kst_now)
        event_data.setdefault('occurUtcDate', utc_now)
        
        # additionalInfo가 딕셔너리면 JSON으로 변환
        if isinstance(event_data.get('additionalInfo'), dict):
            event_data['additionalInfo'] = json.dumps(event_data['additionalInfo'])
        
        # SQL 쿼리 실행
        try:
            with self.conn.cursor() as cursor:
                query = """
                INSERT INTO decision_events (
                    eventId, eventName, eventSymbol, eventPos, holdingPos,
                    prAnswer, prReason, sendExecuteServer, occurKstDate, occurUtcDate,
                    responseTime, entryPrice, currentPrice, additionalInfo
                ) VALUES (
                    %s, %s, %s, %s, %s, 
                    %s, %s, %s, %s, %s, 
                    %s, %s, %s, %s
                )
                """
                
                params = (
                    event_data.get('eventId'),
                    event_data.get('eventName'),
                    event_data.get('eventSymbol'),
                    event_data.get('eventPos'),
                    event_data.get('holdingPos', 'none'),
                    event_data.get('prAnswer'),
                    event_data.get('prReason'),
                    event_data.get('sendExecuteServer', 0),
                    event_data.get('occurKstDate'),
                    event_data.get('occurUtcDate'),
                    event_data.get('responseTime'),
                    event_data.get('entryPrice'),
                    event_data.get('currentPrice'),
                    event_data.get('additionalInfo')
                )
                
                cursor.execute(query, params)
            
            self.conn.commit()
            logger.info(f"이벤트 로그 저장 성공: {event_id}")
            return event_id
            
        except Exception as e:
            logger.error(f"이벤트 로그 저장 중 오류 발생: {e}")
            self.conn.rollback()
            raise
    
    def update_event(self, event_id: str, update_data: Dict[str, Any]) -> bool:
        """
        이벤트 로그 업데이트
        
        Args:
            event_id: 이벤트 ID
            update_data: 업데이트할 데이터
            
        Returns:
            업데이트 성공 여부
        """
        self._ensure_connection()
        
        try:
            # additionalInfo가 딕셔너리면 JSON으로 변환
            if isinstance(update_data.get('additionalInfo'), dict):
                update_data['additionalInfo'] = json.dumps(update_data['additionalInfo'])
            
            # 업데이트할 필드 구성
            set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
            query = f"UPDATE decision_events SET {set_clause} WHERE eventId = %s"
            
            # 파라미터 구성
            params = list(update_data.values())
            params.append(event_id)
            
            # 쿼리 실행
            with self.conn.cursor() as cursor:
                cursor.execute(query, params)
                affected_rows = cursor.rowcount
            
            self.conn.commit()
            
            if affected_rows == 0:
                logger.warning(f"이벤트 ID가 존재하지 않음: {event_id}")
                return False
                
            logger.info(f"이벤트 로그 업데이트 성공: {event_id}")
            return True
            
        except Exception as e:
            logger.error(f"이벤트 로그 업데이트 중 오류 발생: {e}")
            self.conn.rollback()
            return False
    
    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        이벤트 로그 조회
        
        Args:
            event_id: 이벤트 ID
            
        Returns:
            이벤트 데이터 또는 None
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cursor:
                query = "SELECT * FROM decision_events WHERE eventId = %s"
                cursor.execute(query, (event_id,))
                result = cursor.fetchone()
            
            if result:
                logger.info(f"이벤트 로그 조회 성공: {event_id}")
                return result
            else:
                logger.warning(f"이벤트 ID가 존재하지 않음: {event_id}")
                return None
                
        except Exception as e:
            logger.error(f"이벤트 로그 조회 중 오류 발생: {e}")
            return None
    
    def get_events_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        심볼별 이벤트 로그 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            limit: 최대 조회 수
            
        Returns:
            이벤트 데이터 리스트
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cursor:
                query = "SELECT * FROM decision_events WHERE eventSymbol = %s ORDER BY occurUtcDate DESC LIMIT %s"
                cursor.execute(query, (symbol, limit))
                results = cursor.fetchall()
            
            logger.info(f"{symbol} 이벤트 로그 {len(results)}개 조회 성공")
            return results
                
        except Exception as e:
            logger.error(f"이벤트 로그 조회 중 오류 발생: {e}")
            return []
    
    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        최근 이벤트 로그 조회
        
        Args:
            limit: 최대 조회 수
            
        Returns:
            이벤트 데이터 리스트
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cursor:
                query = "SELECT * FROM decision_events ORDER BY occurUtcDate DESC LIMIT %s"
                cursor.execute(query, (limit,))
                results = cursor.fetchall()
            
            logger.info(f"최근 이벤트 로그 {len(results)}개 조회 성공")
            return results
                
        except Exception as e:
            logger.error(f"이벤트 로그 조회 중 오류 발생: {e}")
            return []
    
    def get_events_by_date_range(self, start_date: datetime, end_date: datetime, symbol: str = None) -> List[Dict[str, Any]]:
        """
        날짜 범위별 이벤트 로그 조회
        
        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            symbol: 심볼 (특정 심볼만 조회 시)
            
        Returns:
            이벤트 데이터 리스트
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cursor:
                if symbol:
                    query = """
                    SELECT * FROM decision_events 
                    WHERE occurUtcDate BETWEEN %s AND %s 
                    AND eventSymbol = %s
                    ORDER BY occurUtcDate DESC
                    """
                    cursor.execute(query, (start_date, end_date, symbol))
                else:
                    query = """
                    SELECT * FROM decision_events 
                    WHERE occurUtcDate BETWEEN %s AND %s
                    ORDER BY occurUtcDate DESC
                    """
                    cursor.execute(query, (start_date, end_date))
                
                results = cursor.fetchall()
            
            symbol_str = f"{symbol} " if symbol else ""
            logger.info(f"{symbol_str}날짜 범위 이벤트 로그 {len(results)}개 조회 성공")
            return results
                
        except Exception as e:
            logger.error(f"이벤트 로그 조회 중 오류 발생: {e}")
            return []
    
    def get_events_by_event_type(self, event_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        이벤트 타입별 로그 조회
        
        Args:
            event_type: 이벤트 타입 (예: "open_pos")
            limit: 최대 조회 수
            
        Returns:
            이벤트 데이터 리스트
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cursor:
                query = "SELECT * FROM decision_events WHERE eventName = %s ORDER BY occurUtcDate DESC LIMIT %s"
                cursor.execute(query, (event_type, limit))
                results = cursor.fetchall()
            
            logger.info(f"{event_type} 이벤트 로그 {len(results)}개 조회 성공")
            return results
                
        except Exception as e:
            logger.error(f"이벤트 로그 조회 중 오류 발생: {e}")
            return []
    
    def close(self):
        """데이터베이스 연결 종료"""
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
            logger.info("데이터베이스 연결 종료")
        except Exception as e:
            logger.error(f"데이터베이스 연결 종료 중 오류 발생: {e}")


# 기본 사용 예시
if __name__ == "__main__":
    from config_loader import ConfigLoader
    
    # 설정 로드
    config = ConfigLoader()
    db_config = config.load_config("db_config.json")
    
    if not db_config:
        print("DB 설정 파일이 없습니다. 기본 설정 파일을 생성합니다.")
        # 기본 DB 설정 생성
        db_config = {
            "host": "43.200.99.154",
            "user": "root",
            "password": "center",
            "database": "trading_decisions"
        }
        config.save_config("db_config.json", db_config)
        print("config/db_config.json 파일에 DB 정보를 입력한 후 다시 실행하세요.")
    else:
        try:
            # DB 매니저 생성
            db = DecisionDBManager(
                db_config["host"],
                db_config["user"],
                db_config["password"],
                db_config["database"]
            )
            
            # 테스트 이벤트 로깅
            event_id = db.log_event({
                'eventName': 'open_pos',
                'eventSymbol': 'BTCUSDT',
                'eventPos': 'long',
                'holdingPos': 'none',
                'prAnswer': 'yes',
                'prReason': 'AI가 승인함',
                'sendExecuteServer': 1,
                'responseTime': 0.5,
                'entryPrice': None,
                'currentPrice': 50100.0
            })
            
            # 저장된 이벤트 조회
            event = db.get_event(event_id)
            print(f"저장된 이벤트: {event}")
            
            # 연결 종료
            db.close()
            
        except Exception as e:
            print(f"DB 테스트 중 오류 발생: {e}")