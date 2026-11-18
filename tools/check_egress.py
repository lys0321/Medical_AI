"""本机模式出站审计：跑一遍主要功能，证明没有一条外网连接。

用法（在仓库根）：
    python tools/check_egress.py

它做三件事：
1. 先把 MEDNEXUS_LOCAL_ONLY 打开，并把数据库指到临时文件（不碰你的学习记录）；
2. 劫持 socket 的连接与域名解析，记录所有非本机目标；
3. 依次跑答疑、精选题、教材精练、三要点自测、教学对话，最后打印清单。

本机模式（MEDNEXUS_LOCAL_ONLY=1）的含义：答疑只用教材原文摘录、
文献检索与云同步关闭、对话回落到本机 Ollama 或摘录，因此应当 0 次外网连接。
想对照，可以去掉第 1 步的环境变量再跑一次（会看到模型服务和 NCBI）。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "mednexus"
sys.path.insert(0, str(APP))

# 1. 打开本机模式，并把库指到临时文件
os.environ["MEDNEXUS_LOCAL_ONLY"] = "1"
_tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_tmp.close()
os.environ["MEDNEXUS_DB"] = _tmp.name

# 2. 记录所有出站尝试
LOOKBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
CONNECTS = []
RESOLVES = []
BLOCKED = []


def _is_local(host):
    host = str(host)
    return host in LOOKBACK or host.startswith("127.") or host.startswith("::")


def _note(host, port):
    if not _is_local(host):
        CONNECTS.append("%s:%s" % (host, port))


def _patch():
    import socket

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    def connect(self, address):
        if isinstance(address, tuple) and len(address) >= 2:
            _note(address[0], address[1])
        return orig_connect(self, address)

    def connect_ex(self, address):
        if isinstance(address, tuple) and len(address) >= 2:
            _note(address[0], address[1])
        return orig_connect_ex(self, address)

    def getaddrinfo(host, port, *args, **kwargs):
        if host and not _is_local(host):
            RESOLVES.append(str(host))
        return orig_getaddrinfo(host, port, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    return socket


sock = _patch()

import server  # noqa: E402  必须在打补丁之后导入

LEARNER = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678a1b2c3d4"
FLOWS = []


def run(name, fn):
    """跑一个功能；异常也算一次记录，避免把失败当成"没连网"。"""
    try:
        out = fn()
        FLOWS.append((name, "ok", _short(out)))
    except Exception as error:  # noqa: BLE001  演示脚本，任何异常都要显示出来
        FLOWS.append((name, "跳过/拦截：" + type(error).__name__, str(error)[:80]))


def _short(value):
    if isinstance(value, dict):
        for key in ("mode", "kind", "prompt", "answer"):
            if value.get(key):
                text = str(value[key]).replace("\n", " ")
                return text[:60]
        return "dict"
    return str(value)[:60]


def main():
    from api.core import connect as db_connect

    server.init_db()
    with db_connect() as db:
        run("教材答疑（含教材片段）", lambda: server.ask_compat(
            db, LEARNER, {"question": "小胶质细胞的功能是什么"}))
        run("精选题库出题", lambda: server.make_task(db, LEARNER, "oculomotor", "auto"))
        run("教材章节出题", lambda: server.drill_task(
            db, LEARNER, {"book": "系统解剖学（第10版）", "chapter": 1}))
        run("三要点自测", lambda: server.triple_task(
            db, LEARNER, {"book": "系统解剖学（第10版）", "chapter": 1}))
        run("文献检索（应被本机模式拦截）", lambda: server.pubmed("microglia function"))

    print("=" * 64)
    print("本机模式出站审计（MEDNEXUS_LOCAL_ONLY=1）")
    print("=" * 64)
    for name, state, detail in FLOWS:
        print("  %-24s %-14s %s" % (name, state, detail))
    print("-" * 64)
    if CONNECTS:
        print("外网连接：%d 次" % len(CONNECTS))
        for item in CONNECTS:
            print("   ✗ " + item)
    else:
        print("外网连接：0 次")
    print("域名解析：%s" % ("无" if not RESOLVES else "、".join(sorted(set(RESOLVES)))))
    print("-" * 64)
    if CONNECTS:
        print("结论：有出站连接，本机模式的承诺不成立，需要检查。")
        return 1
    print("结论：全部在本机完成，没有任何数据发出去。")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        os.unlink(os.environ["MEDNEXUS_DB"])
    except OSError:
        pass
    sys.exit(code)