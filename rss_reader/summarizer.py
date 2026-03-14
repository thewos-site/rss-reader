"""LLM 摘要模块 - 支持 Claude/OpenAI"""

from typing import Optional
from .fetcher import Article


class Summarizer:
    """LLM 摘要生成器"""

    def __init__(self, config: dict):
        self.provider = config.get('provider', 'claude')
        self.model = config.get('model', 'claude-sonnet-4-20250514')
        self.api_key = config.get('api_key')
        self.base_url = config.get('base_url')  # 支持自定义 API 地址
        self.openai_api_key = config.get('openai_api_key')
        self.openai_model = config.get('openai_model', 'gpt-4o-mini')
        self.openai_base_url = config.get('openai_base_url')  # 支持 OpenAI 自定义 API 地址
        self.prompt_template = config.get('summary_prompt', self._default_prompt())

        self._client = None

    def _default_prompt(self) -> str:
        return """请用中文为以下文章生成简洁摘要（3-5句话）：
标题：{title}
内容：{content}

要求：突出核心观点，帮助读者快速判断是否值得阅读原文。"""

    def _get_claude_client(self):
        """获取 Claude 客户端"""
        if self._client is None:
            import anthropic
            if self.base_url:
                self._client = anthropic.Anthropic(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            else:
                self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _get_openai_client(self):
        """获取 OpenAI 客户端"""
        if self._client is None:
            import openai
            if self.openai_base_url:
                self._client = openai.OpenAI(
                    api_key=self.openai_api_key,
                    base_url=self.openai_base_url
                )
            else:
                self._client = openai.OpenAI(api_key=self.openai_api_key)
        return self._client

    def _summarize_with_claude(self, prompt: str) -> str:
        """使用 Claude 生成摘要"""
        client = self._get_claude_client()

        message = client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # 处理不同类型的响应内容 (TextBlock, ThinkingBlock 等)
        for block in message.content:
            if hasattr(block, 'text'):
                return block.text
        return str(message.content[0])

    def _summarize_with_openai(self, prompt: str) -> str:
        """使用 OpenAI 生成摘要"""
        client = self._get_openai_client()

        response = client.chat.completions.create(
            model=self.openai_model,
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content

    def summarize(self, article: Article) -> Optional[str]:
        """
        为文章生成摘要

        Args:
            article: 文章对象

        Returns:
            摘要文本，失败返回 None
        """
        # 如果文章内容太短，直接返回
        if len(article.content) < 100:
            return article.content if article.content else "暂无内容摘要"

        # 构建 prompt
        prompt = self.prompt_template.format(
            title=article.title,
            content=article.content
        )

        try:
            if self.provider == 'claude':
                return self._summarize_with_claude(prompt)
            elif self.provider == 'openai':
                return self._summarize_with_openai(prompt)
            else:
                print(f"[警告] 未知的 LLM provider: {self.provider}")
                return None

        except Exception as e:
            print(f"[错误] LLM 摘要失败 ({article.title}): {e}")
            return None

    def summarize_batch(
        self,
        articles: list[Article],
        max_articles: int = 10
    ) -> list[tuple[Article, Optional[str]]]:
        """
        批量生成摘要

        Args:
            articles: 文章列表
            max_articles: 最大处理数量

        Returns:
            (文章, 摘要) 元组列表
        """
        results = []

        for i, article in enumerate(articles[:max_articles]):
            print(f"[摘要] ({i+1}/{min(len(articles), max_articles)}) {article.title[:50]}...")
            summary = self.summarize(article)
            results.append((article, summary))

        return results
