#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日工作台本地服务 (Local Server for Daily Workbench)

提供:
  GET /           -> 提供 dashboard.html (若尚不存在则先生成)
  GET /refresh    -> 调用 workbench.main() 重新抓取所有数据源并重生成 dashboard.html
  其他静态文件    -> 直接 serve

用法:
  python3 server.py              # 默认端口 8787
  python3 server.py --port 9000  # 指定端口
  python3 server.py --no-gen     # 不自动生成(假定 dashboard.html 已存在)

访问: 浏览器打开 http://localhost:8787/
刷新: 页面右上角「↻ 刷新」按钮 -> 触发 /refresh 实时重抓
"""
import argparse
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/refresh" or self.path.startswith("/refresh?"):
            self._run_refresh()
            return
        # 根路径映射到 dashboard.html (http.server 默认找 index.html)
        if self.path == "/":
            self.path = "/dashboard.html"
        return super().do_GET()

    def _run_refresh(self):
        try:
            # 直接在当前进程调用 workbench.main()，复用已装的依赖与逻辑
            import importlib.util
            import sys as _sys
            _old_argv = _sys.argv
            _sys.argv = ["workbench.py"]  # 隔离：workbench.main() 会用 sys.argv
            try:
                spec = importlib.util.spec_from_file_location(
                    "workbench_mod", os.path.join(BASE_DIR, "workbench.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.main()
            finally:
                _sys.argv = _old_argv
            msg = "ok"
            code = 200
        except Exception as e:
            msg = f"error: {e}"
            code = 500
        body = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 静默常规访问日志


def ensure_dashboard(no_gen):
    dash = os.path.join(BASE_DIR, "dashboard.html")
    if no_gen and os.path.isfile(dash):
        return
    if not os.path.isfile(dash):
        print("▶ 首次启动，生成 dashboard.html ...")
        try:
            subprocess.run([PY, os.path.join(BASE_DIR, "workbench.py")], check=True)
        except Exception as e:
            print("⚠️ 生成失败:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-gen", action="store_true",
                    help="假定 dashboard.html 已存在，启动时不自动生成")
    args = ap.parse_args()

    ensure_dashboard(args.no_gen)

    os.chdir(BASE_DIR)
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"✅ 工作台服务已启动: http://localhost:{args.port}/")
    print("   按 Ctrl+C 停止。刷新按钮会触发 /refresh 实时重抓。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 已停止服务")
        httpd.server_close()


if __name__ == "__main__":
    main()
