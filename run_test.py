"""Chạy test RTP trên mọi hệ điều hành (Windows / Linux / macOS).

Cách dùng:
    python run_test.py RTP-base
    python run_test.py RTP-opt
    python run_test.py RTP-base --window 4 --errors 3
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "test_scripts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="RTP-base hoặc RTP-opt")
    ap.add_argument("--window", type=int, default=128)
    ap.add_argument("--errors", default="0123", help="loại lỗi proxy giả lập")
    ap.add_argument("--wait", type=int, default=10, help="số giây chờ tối đa")
    ap.add_argument("--message", default=os.path.join(SCRIPTS, "test_message.txt"))
    ap.add_argument("--recv-port", type=int, default=40000)
    ap.add_argument("--send-port", type=int, default=50000)
    args = ap.parse_args()

    folder = os.path.join(ROOT, args.folder)
    output = os.path.join(folder, "output.txt")
    proxy = "proxy_win.py" if os.name == "nt" else "proxy.py"
    py = sys.executable
    procs = []

    try:
        print("Bước 1: chạy receiver")
        with open(output, "wb") as out_f:
            recv = subprocess.Popen(
                [py, os.path.join(folder, "receiver.py"), "localhost",
                 str(args.recv_port), str(args.window)],
                stdout=out_f, cwd=folder)
            procs.append(recv)
            time.sleep(1)

            print("Bước 2: chạy proxy")
            prox = subprocess.Popen(
                [py, os.path.join(SCRIPTS, proxy), "localhost",
                 str(args.send_port), "localhost", str(args.recv_port),
                 args.errors],
                stdout=subprocess.DEVNULL, cwd=SCRIPTS)
            procs.append(prox)
            time.sleep(1)

            print("Bước 3: chạy sender")
            start = time.time()
            with open(args.message, "rb") as in_f:
                send = subprocess.Popen(
                    [py, os.path.join(folder, "sender.py"), "localhost",
                     str(args.send_port), str(args.window)],
                    stdin=in_f, stdout=subprocess.DEVNULL, cwd=folder)
                procs.append(send)
                try:
                    send.wait(timeout=args.wait)
                    print(f"  sender kết thúc sau {time.time() - start:.1f}s")
                except subprocess.TimeoutExpired:
                    print(f"  sender chưa kết thúc sau {args.wait}s")
            time.sleep(1)  # cho receiver kịp ghi nốt
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        for p in procs:
            p.wait()

    print("Bước 4: so sánh kết quả")
    with open(output, "rb") as a, open(args.message, "rb") as b:
        ok = a.read() == b.read()
    if ok:
        print("\nSUCCESS: Message received matches message sent!\n")
    else:
        print("\nFAILURE: Message received doesn't match message sent.\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
