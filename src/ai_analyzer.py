import requests
import json
import logging
from .config import Config

logger = logging.getLogger(__name__)

class AIAnalyzer:
    def __init__(self):
        self.api_key = Config.AI_API_KEY
        self.base_url = Config.AI_BASE_URL.rstrip('/')
        self.model = Config.AI_MODEL
        self.enabled = Config.AI_ANALYSIS_ENABLED

    def analyze_news(self, title, content):
        """
        Analyzes news using an LLM to determine impact and extract key info.
        Returns a dict with:
        - impact: 'High', 'Medium', 'Low'
        - type: 'Listing', 'Delisting', 'General', 'Partnership', 'Tech', 'Regulation'
        - summary: Short summary (Chinese)
        - coins: List of related coins (e.g., ['BTC', 'ETH'])
        - score: 0-100 impact score
        """
        if not self.enabled or not self.api_key:
            return {
                'impact': 'Unknown',
                'type': 'General',
                'summary': content[:100] + '...',
                'coins': [],
                'score': 0
            }

        prompt = f"""
        你是一个专业的加密货币市场分析师。请分析以下新闻，并以JSON格式返回结果。
        
        新闻标题: {title}
        新闻内容: {content}
        
        请评估该新闻对市场的影响程度，并提取关键信息。
        
        JSON格式要求:
        {{
            "impact": "High" | "Medium" | "Low",  // 只有极具影响力的消息（如主要交易所上币/下币、重大监管政策、知名项目重大更新）才算High
            "type": "Listing" | "Delisting" | "General" | "Partnership" | "Tech" | "Regulation",
            "summary": "简短的中文摘要（50字以内）",
            "coins": ["涉及的代币符号，如BTC"],
            "score": 0-100 // 0为无影响，100为极度重要
        }}
        
        只返回JSON，不要有其他废话。
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            }
            
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            content_str = result['choices'][0]['message']['content'].strip()
            
            # Remove markdown code block markers if present
            if content_str.startswith("```json"):
                content_str = content_str[7:]
            if content_str.endswith("```"):
                content_str = content_str[:-3]
            
            analysis = json.loads(content_str)
            return analysis
            
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {
                'impact': 'Unknown',
                'type': 'General',
                'summary': content[:100] + '...',
                'coins': [],
                'score': 0
            }
