# MCP stdio 握手实测：验证 server.py 工具注册完整
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 用 venv python 启动 server.py（-m server 以模块方式运行，避免路径问题）
proc = subprocess.Popen(
    [
        sys.executable, "-c",
        "import sys; sys.path.insert(0, '.'); from server import build_app; app = build_app(['tutor', 'coder']); app.run()",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

MSG_ID = 0


def send(payload: dict):
    global MSG_ID
    MSG_ID += 1
    payload["id"] = MSG_ID
    proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)


def main():
    # 1) initialize 握手
    r = send({
        "jsonrpc": "2.0", "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "handshake-test", "version": "1.0"},
        },
    })
    server_info = r.get("result", {}).get("serverInfo", {})
    print("1. initialize:", server_info.get("name"), "v" + server_info.get("version", "?"))

    # 2) notifications/initialized
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    # 3) tools/list —— 核心验证
    r = send({"jsonrpc": "2.0", "method": "tools/list", "params": {}})
    tools = r.get("result", {}).get("tools", [])
    names = sorted(t["name"] for t in tools)
    print(f"2. tools/list 共 {len(tools)} 个工具")

    mem = [n for n in names if n.startswith("mem_")]
    tutor = [n for n in names if n.startswith("tutor_")]
    coder = [n for n in names if n.startswith("coder_")]
    print(f"   mem_*  {len(mem)} 个: {mem}")
    print(f"   tutor_* {len(tutor)} 个: {tutor}")
    print(f"   coder_* {len(coder)} 个: {coder}")

    # 4) 断言
    assert len(mem) >= 17, f"mem_* 工具应 ≥17，实际 {len(mem)}"
    assert set(tutor) == {
        "tutor_record_interaction", "tutor_query_errors", "tutor_write_diary", "tutor_end_session",
    }, f"tutor 工具集不完整: {tutor}"
    assert set(coder) == {
        "coder_record_task", "coder_complete_task", "coder_record_review",
    }, f"coder 工具集不完整: {coder}"

    print("\nMCP 服务实测通过 ✅  (mem_* 17 + tutor_* 4 + coder_* 3 = 24 工具)")
    proc.kill()


if __name__ == "__main__":
    main()
