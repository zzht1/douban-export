"""
Douban Insight Web 启动脚本

用法:
    python run.py              # 开发模式
    python run.py --prod       # 生产模式（gunicorn）
"""

import argparse
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Douban Insight Web 启动器")
    parser.add_argument("--prod", action="store_true", help="使用 gunicorn 生产模式")
    parser.add_argument("--port", type=int, default=5000, help="端口号（默认 5000）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--workers", type=int, default=2, help="gunicorn worker 数量")
    args = parser.parse_args()

    # 加载 .env
    from web.config import load_dotenv
    load_dotenv()

    if args.prod:
        # 生产模式：gunicorn
        try:
            from gunicorn.app.wsgiapp import run as gunicorn_run
        except ImportError:
            print("[!] gunicorn 未安装，请运行: pip install gunicorn")
            print("    或使用开发模式: python run.py")
            sys.exit(1)

        os.environ["GUNICORN_CMD_ARGS"] = (
            f"--bind={args.host}:{args.port} "
            f"--workers={args.workers} "
            f"--timeout=300"
        )
        print(f"[*] Douban Insight Web (生产模式)")
        print(f"    地址: http://{args.host}:{args.port}")
        print(f"    Workers: {args.workers}")
        sys.argv = ["gunicorn", "web.app:app"]
        gunicorn_run()
    else:
        # 开发模式
        from web.app import app
        from web import config

        print(f"[*] Douban Insight Web (开发模式)")
        print(f"    地址: http://127.0.0.1:{args.port}")
        print(f"    数据目录: {config.DATA_DIR}")
        print(f"    LLM: {'已配置 (' + config.LLM_MODEL + ')' if config.LLM_API_KEY else '未配置（模板报告）'}")
        print(f"    按 Ctrl+C 停止\n")

        app.run(
            host=args.host,
            port=args.port,
            debug=True,
            use_reloader=True,
        )


if __name__ == "__main__":
    main()
