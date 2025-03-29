import json
import logging
import os
import time
import math
import requests
from typing import Dict, Any, List, Optional, Union

from anthropic import Anthropic

# Create logs directory
os.makedirs("logs", exist_ok=True)

# Logging configuration
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
    Claude AI API Client
    
    A class for generating responses using Anthropic's Claude API
    """
    
    BASE_URL = "https://api.anthropic.com/v1"
    
    def __init__(self, api_key: str, model: str = "claude-3-7-sonnet-20250219"):
        """
        Initialize ClaudeClient
        
        Args:
            api_key: Claude API key
            model: Model to use (default: claude-3-7-sonnet-20250219)
        """
        self.api_key = api_key
        self.model = model
        # Use Anthropic client
        self.client = Anthropic(api_key=api_key)
        # Session for direct HTTP requests
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        })
        
        # Create prompts directory
        os.makedirs("prompts", exist_ok=True)
    
    def verify_entry(self, symbol: str, position_type: str, market_data) -> Dict[str, str]:
        """
        Verify position entry
        
        Args:
            symbol: Symbol (e.g., "BTCUSDT")
            position_type: Position type ("long" or "short")
            market_data: Market data
            
        Returns:
            AI decision ({"Answer": "yes/no", "Reason": "reason"})
        """
        try:
            # Set momentum direction based on position type
            direction = "upward" if position_type == "long" else "downward"
            
            # Convert MarketVO object to dictionary (using data_collector method)
            if hasattr(market_data, 'indicator'):
                # Create temporary data_collector object
                from data_collector import DataCollector
                from bybit_client import BybitClient
                
                # Call formatting method via temporary object
                dc = DataCollector(BybitClient("", ""))
                market_data_dict = dc.format_trading_summary(market_data)
            else:
                # Use as is if already a dictionary
                market_data_dict = market_data
            
            # Extract symbol prefix (e.g., BTCUSDT -> BTC)
            symbol_prefix = symbol.replace("USDT", "").lower()
            
            # Compress JSON data (no indentation, remove spaces between separators)
            compressed_market_data = json.dumps(market_data_dict, ensure_ascii=False, separators=(',', ':'))
            
            # Construct prompt (minimize whitespace, remove unnecessary line breaks)
            prompt = f"""You are an expert crypto futures market analyst assisting a professional trader on Bybit.

CURRENT MARKET DATA:
{compressed_market_data}

QUESTION:
Based on the market data above, should the trader enter a {position_type} position on {symbol} perpetual futures now? 
Analyze whether current market conditions are favorable for entering a {direction} trend.

Your analysis should consider:
- Price action and recent momentum
- Technical indicators
- Current market structure and volume patterns
- Potential support/resistance levels

I need your most accurate and intelligent assessment using your full analytical capabilities as Claude 3.7 Sonnet.

Please provide your decision in JSON format:
{{"Answer":"yes/no","Reason":"Brief explanation of your decision"}}"""
            
            # Save request (include original data format)
            os.makedirs("prompts", exist_ok=True)
            with open(f"prompts/{symbol_prefix}_request.txt", 'w', encoding='utf-8') as f:
                # Also save original formatted data (for debugging)
                original_format = json.dumps(market_data_dict, indent=2, ensure_ascii=False)
                f.write(f"# Original data (for debugging)\n{original_format}\n\n# Actual prompt sent\n{prompt}")
            
            # Generate AI response (set temperature=1.0 for extended thinking)
            response_text = self.generate_response(prompt, temperature=1.0)
            
            # Save response
            with open(f"prompts/{symbol_prefix}_response.txt", 'w', encoding='utf-8') as f:
                f.write(response_text)
            
            # Parse JSON response
            try:
                # Remove non-JSON text
                json_text = response_text
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()
                
                # Parse response
                response_data = json.loads(json_text)
                
                # Validate response format
                if "Answer" not in response_data or "Reason" not in response_data:
                    raise ValueError("Response format is incorrect.")
                
                # Normalize Answer to yes or no
                answer = response_data["Answer"].lower().strip()
                if "yes" in answer:
                    response_data["Answer"] = "yes"
                else:
                    response_data["Answer"] = "no"
                
                return response_data
                    
            except Exception as parse_error:
                logger.error(f"Error parsing AI response: {parse_error}")
                logger.error(f"Original response: {response_text}")
                
                # Return default response
                if "yes" in response_text.lower():
                    return {"Answer": "yes", "Reason": "yes"}
                else:
                    return {"Answer": "no", "Reason": "Failed to parse response"}
                
        except Exception as e:
            logger.exception(f"Error during entry verification: {e}")
            return {"Answer": "no", "Reason": f"Error occurred: {str(e)}"}


    def verify_trend_touch(self, symbol: str, position: Dict[str, Any], market_data) -> Dict[str, str]:
        """
        Verify trendline touch decision
        
        Args:
            symbol: Symbol (e.g., "BTCUSDT")
            position: Current position information
            market_data: Market data
            
        Returns:
            AI decision ({"Answer": "yes/no", "Reason": "reason"})
        """
        try:
            # Convert MarketVO object to dictionary (using data_collector method)
            if hasattr(market_data, 'indicator'):
                # Create temporary data_collector object
                from data_collector import DataCollector
                from bybit_client import BybitClient
                
                # Call formatting method via temporary object
                dc = DataCollector(BybitClient("", ""))
                market_data_dict = dc.format_trading_summary(market_data)
            else:
                # Use as is if already a dictionary
                market_data_dict = market_data
            
            # Extract symbol prefix (e.g., BTCUSDT -> BTC)
            symbol_prefix = symbol.replace("USDT", "").lower()
            
            # Get position details
            position_type = position.get("position_type", "unknown")
            entry_price = position.get("entry_price", 0)
            
            # Compress JSON data (no indentation, remove spaces between separators)
            compressed_market_data = json.dumps(market_data_dict, ensure_ascii=False, separators=(',', ':'))
            compressed_position = json.dumps(position, ensure_ascii=False, separators=(',', ':'))
            
            # Construct prompt (minimize whitespace, remove unnecessary line breaks)
            prompt = f"""You are an expert crypto futures market analyst assisting a professional trader on Bybit.

CURRENT MARKET DATA:
{compressed_market_data}

CURRENT POSITION:
{compressed_position}

SITUATION:
The trader is currently in a {position_type} position on {symbol} perpetual futures entered at {entry_price}. 
The price has just touched a trendline, which is a critical decision point.

QUESTION:
Based on the comprehensive market data above and the current position information, what is the optimal decision for this {position_type} position that was entered at {entry_price}?

Please provide detailed analysis considering:
1. Has the original thesis for this trade been validated or invalidated since entry?
2. Does the trendline touch represent a natural exit point or a continuation signal?
3. Do the recent candle patterns on the 5-minute and 15-minute timeframes suggest continuation or reversal?
4. Have any significant support/resistance levels been broken since entry?

Your analysis should consider:
- Current price in relation to entry price
- Whether original trend is still intact
- Volume patterns and momentum indicators
- Risk of reversal versus potential for continuation
- Overall market conditions since entry

I need your most accurate and intelligent assessment using your full analytical capabilities as Claude 3.7 Sonnet.

Please provide your decision in JSON format:
{{"Answer":"yes/no","Reason":"Brief explanation of your decision (yes = close position, no = maintain position)"}}"""
            
            # Save request (include original data format)
            os.makedirs("prompts", exist_ok=True)
            with open(f"prompts/{symbol_prefix}_trend_request.txt", 'w', encoding='utf-8') as f:
                # Also save original formatted data (for debugging)
                original_market = json.dumps(market_data_dict, indent=2, ensure_ascii=False)
                original_position = json.dumps(position, indent=2, ensure_ascii=False)
                f.write(f"# Original data (for debugging)\n## Market data\n{original_market}\n\n## Position info\n{original_position}\n\n# Actual prompt sent\n{prompt}")
            
            # Generate AI response (set temperature=1.0 for extended thinking)
            response_text = self.generate_response(prompt, temperature=1.0)
            
            # Save response
            with open(f"prompts/{symbol_prefix}_trend_response.txt", 'w', encoding='utf-8') as f:
                f.write(response_text)
            
            # Parse JSON response
            try:
                # Remove non-JSON text
                json_text = response_text
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()
                
                # Parse response
                response_data = json.loads(json_text)
                
                # Validate response format
                if "Answer" not in response_data or "Reason" not in response_data:
                    raise ValueError("Response format is incorrect.")
                
                # Normalize Answer to yes or no
                answer = response_data["Answer"].lower().strip()
                if "yes" in answer:
                    response_data["Answer"] = "yes"
                else:
                    response_data["Answer"] = "no"
                
                return response_data
                    
            except Exception as parse_error:
                logger.error(f"Error parsing AI response: {parse_error}")
                logger.error(f"Original response: {response_text}")
                
                # Return default response
                if "yes" in response_text.lower():
                    return {"Answer": "yes", "Reason": "yes"}
                else:
                    return {"Answer": "no", "Reason": "Failed to parse response"}
                
        except Exception as e:
            logger.exception(f"Error during trendline touch verification: {e}")
            return {"Answer": "no", "Reason": f"Error occurred: {str(e)}"}


    def generate_response(self, prompt: str, max_tokens: int = 20000, temperature: float = 1.0) -> str:
        """
        Send prompt to Claude AI and generate response
        
        Args:
            prompt: Prompt text
            max_tokens: Maximum number of tokens (default: 20000, must be greater than thinking.budget_tokens)
            temperature: Sampling temperature (default: 1.0 - leverages Claude's extended thinking mode)
            
        Returns:
            Generated response text
        """
        # thinking.budget_tokens must be less than max_tokens
        thinking_budget = min(16000, max_tokens - 4000)  # Set at least 4000 less than max_tokens
        
        try:
            logger.info(f"Claude API request (model: {self.model}, max_tokens: {max_tokens}, thinking_budget: {thinking_budget}, temperature: {temperature})")
            
            # API request (use Anthropic SDK, activate reasoning mode)
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
            
            # Extract text from response (handle API response structure changes)
            full_text = ""
            if response.content:
                for content_block in response.content:
                    if hasattr(content_block, 'text'):
                        full_text += content_block.text
                    elif hasattr(content_block, 'value'):
                        full_text += content_block.value
                    elif isinstance(content_block, dict) and 'text' in content_block:
                        full_text += content_block['text']
            
            logger.info(f"Claude API response received (length: {len(full_text)} characters)")
            return full_text
            
        except Exception as e:
            logger.exception(f"Error during Claude API request: {e}")
            # Retry up to 3 times
            for i in range(3):
                try:
                    logger.info(f"Claude API retry ({i+1}/3)")
                    time.sleep(2)  # Wait before retry
                    
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
                    
                    # Extract text from response (handle API response structure changes)
                    full_text = ""
                    if response.content:
                        for content_block in response.content:
                            if hasattr(content_block, 'text'):
                                full_text += content_block.text
                            elif hasattr(content_block, 'value'):
                                full_text += content_block.value
                            elif isinstance(content_block, dict) and 'text' in content_block:
                                full_text += content_block['text']
                    
                    logger.info(f"Claude API response received (length: {len(full_text)} characters)")
                    return full_text
                    
                except Exception as retry_error:
                    logger.exception(f"Error during Claude API retry: {retry_error}")
                    continue
            
            return f"Error: {str(e)}"


# Basic usage example
if __name__ == "__main__":
    from config_loader import ConfigLoader
    
    # Load configuration
    config = ConfigLoader()
    api_keys = config.load_config("api_keys.json")
    
    # Create Claude client
    client = ClaudeClient(
        api_keys["claude_api"]["key"],
        api_keys["claude_api"]["model"]
    )
    
    # Test prompt
    test_prompt = """
    This is a simple test message.
    """
    
    # Generate response
    response = client.generate_response(test_prompt)
    print(f"\nResponse:\n{response}")