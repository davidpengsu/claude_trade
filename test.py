# db_test.py
import pymysql
import time

print("===== PyMySQL 연결 테스트 시작 =====")

try:
    print("데이터베이스 연결 시도 중...")
    # 연결 설정
    conn = pymysql.connect(
        host="43.200.99.154",
        user="root",
        password="center",
        database="trading_decisions",
        port=3306,
        charset="utf8mb4",
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )
    print("데이터베이스 연결 성공!")
    
    # 테이블 존재 여부 확인
    with conn.cursor() as cursor:
        cursor.execute("SHOW TABLES LIKE 'decision_events'")
        table_exists = cursor.fetchone()
        
        if table_exists:
            print("decision_events 테이블 존재함")
            
            # 테이블 구조 확인
            cursor.execute("DESCRIBE decision_events")
            columns = cursor.fetchall()
            print(f"테이블 구조 ({len(columns)}개 컬럼):")
            for col in columns:
                print(f"  - {col['Field']}: {col['Type']}")
            
            # 레코드 수 확인
            cursor.execute("SELECT COUNT(*) as count FROM decision_events")
            count = cursor.fetchone()['count']
            print(f"테이블에 {count}개의 레코드가 있습니다")
            
            # 샘플 데이터 확인
            if count > 0:
                cursor.execute("SELECT * FROM decision_events ORDER BY occurUtcDate DESC LIMIT 1")
                latest = cursor.fetchone()
                print("\n최근 레코드 정보:")
                print(f"  - 이벤트 ID: {latest.get('eventId')}")
                print(f"  - 이벤트 이름: {latest.get('eventName')}")
                print(f"  - 심볼: {latest.get('eventSymbol')}")
                print(f"  - 발생 시간: {latest.get('occurUtcDate')}")
        else:
            print("decision_events 테이블이 없습니다. 테이블을 생성해야 합니다.")
            print("db_init.sql 스크립트를 실행하세요.")
    
    # 연결 종료
    conn.close()
    print("연결 종료됨")
except pymysql.Error as err:
    print(f"MySQL 오류: {err}")
except Exception as e:
    print(f"일반 오류: {e}")

print("===== 테스트 완료 =====")