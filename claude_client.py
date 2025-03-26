import json
import logging
import os
import time
import math
import requests
from typing import Dict, Any, List, Optional, Union

from anthropic import Anthropic

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/claude_client.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("claude_client")

class ClaudeClient:
    """
    Claude AI API 클라이언트
    
    Anthropic의 Claude API를 이용해 응답을 생성하는 클래스
    """
    
    BASE_URL = "https://api.anthropic.com/v1"
    
    def __init__(self, api_key: str, model: str = "claude-3-7-sonnet-20250219"):
        """
        ClaudeClient 초기화
        
        Args:
            api_key: Claude API 키
            model: 사용할 모델 (기본값: claude-3-7-sonnet-20250219)
        """
        self.api_key = api_key
        self.model = model
        # Anthropic 클라이언트 사용
        self.client = Anthropic(api_key=api_key)
        # 직접 HTTP 요청을 보내기 위한 세션
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        })
        
        # prompts 디렉토리 생성
        os.makedirs("prompts", exist_ok=True)
    
    def verify_entry(self, symbol: str, position_type: str, market_data) -> Dict[str, str]:
        """
        포지션 진입 검증
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position_type: 포지션 타입 ("long" 또는 "short")
            market_data: 시장 데이터
            
        Returns:
            AI 결정 ({"Answer": "yes/no", "Reason": "이유"})
        """
        try:
            # 포지션 방향에 따른 모멘텀 방향 설정
            direction = "상승" if position_type == "long" else "하락"
            
            # MarketVO 객체를 딕셔너리로 변환 (data_collector의 메서드 사용)
            if hasattr(market_data, 'indicator'):
                # data_collector 객체 임시 생성
                from data_collector import DataCollector
                from bybit_client import BybitClient
                
                # 임시 객체를 통해 포맷팅 메서드 호출
                dc = DataCollector(BybitClient("", ""))
                market_data_dict = dc.format_trading_summary(market_data)
            else:
                # 이미 딕셔너리인 경우 그대로 사용
                market_data_dict = market_data
            
            # 심볼 접두어 추출 (예: BTCUSDT -> BTC)
            symbol_prefix = symbol.replace("USDT", "").lower()
            
            # JSON 데이터 압축 (indent 없음, 구분자 사이 공백 제거)
            compressed_market_data = json.dumps(market_data_dict, ensure_ascii=False, separators=(',', ':'))
            
            # 공백 최소화를 위해 프롬프트 구성 (불필요한 줄바꿈 제거)
            prompt = f"""현재 시장 상황: {compressed_market_data}
    너는 코인트레이더의 전략적이고 정교한 선택을 도와주는 전문가다.
    현재상황에서 [{position_type}] 포지션을 진입하는것은 
    1%이상의 [{direction}] 모멘텀을 먹을수있는것에대해서 가능할것같아?
    아래 json 형식에 맞추어서 무조건 yes 라고 답하세요.
    {{"Answer":"yes or no","Reason":"if yes, just say yes, no일경우 왜 no 결정을 내렸는지 상세 이유작성"}}"""
            
            # 요청 저장 (원본 형식의 데이터 포함)
            os.makedirs("prompts", exist_ok=True)
            with open(f"prompts/{symbol_prefix}_request.txt", 'w', encoding='utf-8') as f:
                # 원본 포맷의 데이터도 함께 저장 (디버깅용)
                original_format = json.dumps(market_data_dict, indent=2, ensure_ascii=False)
                f.write(f"# 원본 데이터 (디버깅용)\n{original_format}\n\n# 실제 보낸 프롬프트\n{prompt}")
            
            # AI 응답 생성 (temperature=1로 설정)
            response_text = self.generate_response(prompt, temperature=1.0)
            
            # 응답 저장
            with open(f"prompts/{symbol_prefix}_response.txt", 'w', encoding='utf-8') as f:
                f.write(response_text)
            
            # JSON 파싱
            try:
                # JSON 형식이 아닌 텍스트 제거
                json_text = response_text
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()
                
                # 응답 파싱
                response_data = json.loads(json_text)
                
                # 응답 형식 검증
                if "Answer" not in response_data or "Reason" not in response_data:
                    raise ValueError("응답 형식이 올바르지 않습니다.")
                
                # Answer를 yes 또는 no로 정규화
                answer = response_data["Answer"].lower().strip()
                if "yes" in answer:
                    response_data["Answer"] = "yes"
                else:
                    response_data["Answer"] = "no"
                
                return response_data
                    
            except Exception as parse_error:
                logger.error(f"AI 응답 파싱 중 오류 발생: {parse_error}")
                logger.error(f"원본 응답: {response_text}")
                
                # 기본 응답 반환
                if "yes" in response_text.lower():
                    return {"Answer": "yes", "Reason": "yes"}
                else:
                    return {"Answer": "no", "Reason": "응답 파싱 실패"}
                
        except Exception as e:
            logger.exception(f"진입 검증 중 오류 발생: {e}")
            return {"Answer": "no", "Reason": f"오류 발생: {str(e)}"}


    def verify_trend_touch(self, symbol: str, position: Dict[str, Any], market_data) -> Dict[str, str]:
        """
        추세선 터치 검증
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position: 현재 포지션 정보
            market_data: 시장 데이터
            
        Returns:
            AI 결정 ({"Answer": "yes/no", "Reason": "이유"})
        """
        try:
            # MarketVO 객체를 딕셔너리로 변환 (data_collector의 메서드 사용)
            if hasattr(market_data, 'indicator'):
                # data_collector 객체 임시 생성
                from data_collector import DataCollector
                from bybit_client import BybitClient
                
                # 임시 객체를 통해 포맷팅 메서드 호출
                dc = DataCollector(BybitClient("", ""))
                market_data_dict = dc.format_trading_summary(market_data)
            else:
                # 이미 딕셔너리인 경우 그대로 사용
                market_data_dict = market_data
            
            # 심볼 접두어 추출 (예: BTCUSDT -> BTC)
            symbol_prefix = symbol.replace("USDT", "").lower()
            
            # JSON 데이터 압축 (indent 없음, 구분자 사이 공백 제거)
            compressed_market_data = json.dumps(market_data_dict, ensure_ascii=False, separators=(',', ':'))
            compressed_position = json.dumps(position, ensure_ascii=False, separators=(',', ':'))
            
            # 공백 최소화를 위해 프롬프트 구성 (불필요한 줄바꿈 제거)
            prompt = f"""현재 시장 상황: {compressed_market_data}
    현재 포지션 정보: {compressed_position}
    너는 코인트레이더의 전략적이고 정교한 선택을 도와주는 전문가다.
    현재 [{position.get("entry_price", 0)}]에 [{position.get("position_type", "unknown")}] 포지션을 진입했는데,
    추세선에 닿았고 현재 시장 상황은 위와 같아.
    현재 포지션을 청산하고 거래를 마무리하는 것이 좋을까? 아니면 포지션을 유지하는 것이 더 좋을까?
    아래 json 형식에 맞추어서 답하고:
    {{"Answer":"yes or no (yes=청산, no=유지)","Reason":"if yes, just say yes, no일경우 왜 포지션을 유지하는 것이 좋은지 상세 이유작성"}}"""
            
            # 요청 저장 (원본 형식의 데이터 포함)
            os.makedirs("prompts", exist_ok=True)
            with open(f"prompts/{symbol_prefix}_trend_request.txt", 'w', encoding='utf-8') as f:
                # 원본 포맷의 데이터도 함께 저장 (디버깅용)
                original_market = json.dumps(market_data_dict, indent=2, ensure_ascii=False)
                original_position = json.dumps(position, indent=2, ensure_ascii=False)
                f.write(f"# 원본 데이터 (디버깅용)\n## 시장 데이터\n{original_market}\n\n## 포지션 정보\n{original_position}\n\n# 실제 보낸 프롬프트\n{prompt}")
            
            # AI 응답 생성 (temperature=1로 설정)
            response_text = self.generate_response(prompt, temperature=1.0)
            
            # 응답 저장
            with open(f"prompts/{symbol_prefix}_trend_response.txt", 'w', encoding='utf-8') as f:
                f.write(response_text)
            
            # JSON 파싱
            try:
                # JSON 형식이 아닌 텍스트 제거
                json_text = response_text
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()
                
                # 응답 파싱
                response_data = json.loads(json_text)
                
                # 응답 형식 검증
                if "Answer" not in response_data or "Reason" not in response_data:
                    raise ValueError("응답 형식이 올바르지 않습니다.")
                
                # Answer를 yes 또는 no로 정규화
                answer = response_data["Answer"].lower().strip()
                if "yes" in answer:
                    response_data["Answer"] = "yes"
                else:
                    response_data["Answer"] = "no"
                
                return response_data
                    
            except Exception as parse_error:
                logger.error(f"AI 응답 파싱 중 오류 발생: {parse_error}")
                logger.error(f"원본 응답: {response_text}")
                
                # 기본 응답 반환
                if "yes" in response_text.lower():
                    return {"Answer": "yes", "Reason": "yes"}
                else:
                    return {"Answer": "no", "Reason": "응답 파싱 실패"}
                
        except Exception as e:
            logger.exception(f"추세선 검증 중 오류 발생: {e}")
            return {"Answer": "no", "Reason": f"오류 발생: {str(e)}"}


    def generate_response(self, prompt: str, max_tokens: int = 20000, temperature: float = 1.0) -> str:
        """
        Claude AI에 프롬프트를 보내고 응답 생성
        
        Args:
            prompt: 프롬프트 텍스트
            max_tokens: 최대 토큰 수 (기본값: 20000, thinking.budget_tokens보다 커야 함)
            temperature: 샘플링 온도 (기본값: 1.0 - 더 창의적인 응답)
            
        Returns:
            생성된 응답 텍스트
        """
        # thinking.budget_tokens는 max_tokens보다 작아야 함
        thinking_budget = min(16000, max_tokens - 4000)  # max_tokens보다 적어도 4000 작게 설정
        
        try:
            logger.info(f"Claude API 요청 (모델: {self.model}, max_tokens: {max_tokens}, thinking_budget: {thinking_budget}, temperature: {temperature})")
            
            # API 요청 (Anthropic SDK 사용, reasoning mode 활성화)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking={
                    "type": "enabled",
                    "budget_tokens": thinking_budget
                },
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # 응답에서 텍스트 추출 (API 응답 구조 변경 대응)
            full_text = ""
            if response.content:
                for content_block in response.content:
                    if hasattr(content_block, 'text'):
                        full_text += content_block.text
                    elif hasattr(content_block, 'value'):
                        full_text += content_block.value
                    elif isinstance(content_block, dict) and 'text' in content_block:
                        full_text += content_block['text']
            
            logger.info(f"Claude API 응답 수신 완료 (길이: {len(full_text)}자)")
            return full_text
            
        except Exception as e:
            logger.exception(f"Claude API 요청 중 오류 발생: {e}")
            # 최대 3번 재시도
            for i in range(3):
                try:
                    logger.info(f"Claude API 재시도 ({i+1}/3)")
                    time.sleep(2)  # 재시도 전 대기
                    
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        thinking={
                            "type": "enabled",
                            "budget_tokens": thinking_budget
                        },
                        messages=[
                            {"role": "user", "content": prompt}
                        ]
                    )
                    
                    # 응답에서 텍스트 추출 (API 응답 구조 변경 대응)
                    full_text = ""
                    if response.content:
                        for content_block in response.content:
                            if hasattr(content_block, 'text'):
                                full_text += content_block.text
                            elif hasattr(content_block, 'value'):
                                full_text += content_block.value
                            elif isinstance(content_block, dict) and 'text' in content_block:
                                full_text += content_block['text']
                    
                    logger.info(f"Claude API 응답 수신 완료 (길이: {len(full_text)}자)")
                    return full_text
                    
                except Exception as retry_error:
                    logger.exception(f"Claude API 재시도 중 오류 발생: {retry_error}")
                    continue
            
            return f"Error: {str(e)}"


# 기본 사용 예시
if __name__ == "__main__":
    from config_loader import ConfigLoader
    
    # 설정 로드
    config = ConfigLoader()
    api_keys = config.load_config("api_keys.json")
    
    # Claude 클라이언트 생성
    client = ClaudeClient(
        api_keys["claude_api"]["key"],
        api_keys["claude_api"]["model"]
    )
    
    # 테스트 프롬프트
    test_prompt = """
    간단한 테스트 메시지입니다.
    """
    
    # 응답 생성
    response = client.generate_response(test_prompt)
    print(f"\n응답:\n{response}")