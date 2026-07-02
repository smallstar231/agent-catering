"""
全服务启动脚本（Monorepo 版）
一键启动 Python Agent + Spring Boot + Vue 前端
要求：
  1. Spring Boot: 先执行 cd sky-take-out && mvn package -DskipTests
  2. Vue 前端: 先执行 cd sky-admin-front && yarn install (或 npm install)
用法：
  python start_all_services.py
"""

import subprocess
import time
import os
import sys
import shutil

# 自动获取项目根目录（脚本所在目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def find_java():
    """从 PATH 或常见位置查找 java"""
    java_in_path = shutil.which("java")
    if java_in_path:
        return java_in_path
    # 尝试常见安装路径
    candidates = [
        os.path.expanduser("~/.sdkman/candidates/java/current/bin/java"),
        "/usr/lib/jvm/java-17-openjdk-amd64/bin/java",
        "/usr/local/opt/openjdk/bin/java",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "java"  # fallback


def start_python_agent():
    log("Starting Python Agent on :8000...")
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'api_service:app', '--host', '0.0.0.0', '--port', '8000'],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    )
    log(f"Python Agent PID: {proc.pid}")
    return proc


def start_spring_boot():
    log("Starting Spring Boot on :8080...")
    java = find_java()
    jar = os.path.join(PROJECT_ROOT, 'sky-take-out', 'sky-server', 'target', 'sky-server-1.0-SNAPSHOT.jar')
    logf = os.path.join(PROJECT_ROOT, 'springboot.log')
    open(logf, 'w').close()
    proc = subprocess.Popen(
        [java, '-jar', jar, '--server.port=8080'],
        stdout=open(logf, 'w'), stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    )
    log(f"Spring Boot PID: {proc.pid}")
    return proc


def start_vue():
    log("Starting Vue on :8888...")
    vue_dir = os.path.join(PROJECT_ROOT, 'sky-admin-front')
    logf = os.path.join(vue_dir, 'vue-dev.log')
    open(logf, 'w').close()
    env = os.environ.copy()
    env['NODE_OPTIONS'] = '--openssl-legacy-provider'
    proc = subprocess.Popen(
        ['cmd.exe', '/c', 'node node_modules/@vue/cli-service/bin/vue-cli-service.js serve'],
        cwd=vue_dir, stdout=open(logf, 'w'), stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    )
    log(f"Vue PID: {proc.pid}")
    return proc


if __name__ == '__main__':
    log("=== Starting all services ===")
    start_python_agent()
    time.sleep(2)
    start_spring_boot()
    time.sleep(2)
    start_vue()
    log("All services launched! Waiting 30s for startup...")
    time.sleep(30)
    log("Done! Check:\n"
        "  Python Agent: http://localhost:8000/\n"
        "  Spring Boot:  http://localhost:8080/admin/employee/login\n"
        "  Vue Frontend: http://localhost:8888/")
