#!/usr/bin/env python3
"""RSS AI Reader - 主入口"""

import argparse
import os
import re
import time
from pathlib import Path

import yaml
import schedule

from rss_reader.fetcher import fetch_all_feeds, filter_by_age
from rss_reader.storage import Storage
from rss_reader.summarizer import Summarizer
from rss_reader.notifier import Notifier


def load_config(config_path: str = "config.yaml") -> dict:
    """
    加载配置文件，支持环境变量替换

    配置文件中 ${VAR_NAME} 会被替换为对应的环境变量值
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 替换环境变量 ${VAR_NAME}
    def replace_env(match):
        var_name = match.group(1)
        return os.environ.get(var_name, '')

    content = re.sub(r'\$\{(\w+)\}', replace_env, content)

    return yaml.safe_load(content)


def run_once(config: dict, storage: Storage):
    """执行一次抓取-摘要-推送流程"""
    print("\n" + "=" * 50)
    print("🚀 开始运行 RSS AI Reader")
    print("=" * 50)

    # 1. 抓取所有 feeds
    print("\n📡 [步骤1] 抓取 RSS Feeds...")
    feeds = config.get('feeds', [])
    if not feeds:
        print("[警告] 没有配置任何 feeds")
        return

    all_articles = fetch_all_feeds(feeds)
    print(f"共获取 {len(all_articles)} 篇文章")

    # 2. 按时间过滤（只处理最近N小时的文章）
    max_age_hours = config.get('schedule', {}).get('max_age_hours', 24)
    recent_articles = filter_by_age(all_articles, max_age_hours)
    print(f"最近 {max_age_hours} 小时内: {len(recent_articles)} 篇")

    # 3. 过滤已处理的文章
    print("\n🔍 [步骤2] 过滤已处理文章...")
    new_articles = storage.filter_new_articles(recent_articles)
    print(f"发现 {len(new_articles)} 篇新文章")

    if not new_articles:
        print("没有新文章需要处理")
        return

    # 4. 限制处理数量
    max_articles = config.get('schedule', {}).get('max_articles_per_run', 10)
    articles_to_process = new_articles[:max_articles]
    print(f"本次处理 {len(articles_to_process)} 篇")

    # 5. 初始化 LLM 摘要器
    print("\n🤖 [步骤3] 生成摘要...")
    llm_config = config.get('llm', {})
    summarizer = Summarizer(llm_config)

    # 6. 初始化通知器
    notify_config = config.get('notify', {})
    notifier = Notifier(notify_config)

    if not notifier.has_notifiers:
        print("[警告] 没有启用任何推送渠道，摘要将只保存到数据库")

    # 7. 处理每篇文章
    success_count = 0
    for i, article in enumerate(articles_to_process, 1):
        print(f"\n--- 文章 {i}/{len(articles_to_process)} ---")
        print(f"标题: {article.title[:60]}...")
        print(f"来源: {article.feed_name}")

        # 生成摘要
        summary = summarizer.summarize(article)
        if summary:
            print(f"摘要: {summary[:100]}...")

            # 推送通知
            if notifier.has_notifiers:
                results = notifier.notify(article, summary)
                for channel, ok in results.items():
                    status = "✅" if ok else "❌"
                    print(f"  {status} {channel}")

            # 标记为已处理
            storage.mark_processed(article, summary)
            success_count += 1
        else:
            print("[跳过] 摘要生成失败")
            # 即使摘要失败也标记为已处理，避免重复尝试
            storage.mark_processed(article, None)

    # 8. 打印统计
    print("\n" + "=" * 50)
    print(f"✅ 完成! 成功处理 {success_count}/{len(articles_to_process)} 篇文章")
    stats = storage.get_stats()
    print(f"📊 数据库共记录 {stats['total_articles']} 篇文章")
    print("=" * 50)


def run_scheduler(config: dict, storage: Storage):
    """运行定时调度"""
    interval = config.get('schedule', {}).get('interval_minutes', 60)

    print(f"⏰ 启动定时任务，每 {interval} 分钟执行一次")
    print("按 Ctrl+C 停止\n")

    # 立即执行一次
    run_once(config, storage)

    # 设置定时任务
    schedule.every(interval).minutes.do(run_once, config=config, storage=storage)

    while True:
        schedule.run_pending()
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(
        description='RSS AI Reader - 自动抓取、摘要、推送',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --once          # 执行一次
  python main.py                 # 启动定时任务
  python main.py --config my.yaml  # 使用自定义配置
  python main.py --stats         # 查看统计信息
        """
    )

    parser.add_argument(
        '--config', '-c',
        default='config.yaml',
        help='配置文件路径 (默认: config.yaml)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='只执行一次，不启动定时任务'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='显示统计信息并退出'
    )
    parser.add_argument(
        '--db',
        default='rss_reader.db',
        help='数据库文件路径 (默认: rss_reader.db)'
    )

    args = parser.parse_args()

    # 检查配置文件
    if not Path(args.config).exists():
        print(f"[错误] 配置文件不存在: {args.config}")
        print("请复制 config.yaml.example 并修改为您的配置")
        return 1

    # 加载配置
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"[错误] 加载配置文件失败: {e}")
        return 1

    # 初始化存储
    storage = Storage(args.db)

    # 显示统计信息
    if args.stats:
        stats = storage.get_stats()
        print("\n📊 RSS Reader 统计")
        print("=" * 40)
        print(f"总文章数: {stats['total_articles']}")
        print("\n按来源统计:")
        for feed, count in stats['by_feed'].items():
            print(f"  - {feed}: {count}")
        return 0

    # 执行
    try:
        if args.once:
            run_once(config, storage)
        else:
            run_scheduler(config, storage)
    except KeyboardInterrupt:
        print("\n\n👋 已停止")
        return 0

    return 0


if __name__ == '__main__':
    exit(main())
