"""
配置管理

通过环境变量或 .env 文件加载配置。
"""

import os
from pathlib import Path

# 项目根目录（douban-export/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── LLM 配置 ──────────────────────────────────────────────
# 兼容 OpenAI / DeepSeek / 其他 OpenAI-compatible API
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# ── 爬取配置 ──────────────────────────────────────────────
PAGE_SIZE = 30        # 每页条目数
CACHE_TTL_HOURS = 24  # 缓存有效期（小时）

# 并发爬取：同时爬取不同子站（movie/book/music），同一子站内仍逐页串行
CONCURRENT_SCRAPERS = 3

# 智能延迟：有 Cookie 代表已登录，请求可以更激进
SCRAPE_DELAY_MIN = 2          # 无 Cookie 最小等待秒数
SCRAPE_DELAY_MAX = 4          # 无 Cookie 最大等待秒数
SCRAPE_DELAY_MIN_COOKIE = 1   # 有 Cookie 最小等待秒数
SCRAPE_DELAY_MAX_COOKIE = 2   # 有 Cookie 最大等待秒数

# ── 服务器配置 ──────────────────────────────────────────────
MAX_WORKERS = 2       # 并发分析任务数
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# ── 豆瓣请求头 ──────────────────────────────────────────────
DOUBAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://movie.douban.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 加载 .env 文件（如果存在）
def load_dotenv():
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
                    # 更新模块级变量，保持类型一致
                    g = globals()
                    if key in g:
                        old = g[key]
                        if isinstance(old, int):
                            try:
                                g[key] = int(value)
                            except ValueError:
                                g[key] = value
                        elif isinstance(old, bool):
                            g[key] = value in ("1", "true", "True", "yes")
                        else:
                            g[key] = value

load_dotenv()
