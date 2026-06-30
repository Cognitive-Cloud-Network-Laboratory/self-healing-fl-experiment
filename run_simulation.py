import subprocess
import time
import sys
import os

print("🟢 เริ่มต้นจำลองสภาพแวดล้อม Federated Learning...")
print("=" * 50)

processes = []

# 1. เปิด Server
print("🌐 กำลังรัน Server...")
server_proc = subprocess.Popen(
    ["python", "server.py"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1
)
processes.append(("Server", server_proc))
time.sleep(3) # รอให้ Server เปิดเสร็จ

# 2. เปิดโหนดคนดี (Benign Clients) 8 เครื่อง
print("🛡️ กำลังรันโหนดปกติ (Benign Clients) 8 เครื่อง...")
for i in range(8):
    proc = subprocess.Popen(
        ["python", "client.py"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    processes.append((f"Benign-{i+1}", proc))
    time.sleep(0.5)

# 3. เปิดโหนดผู้ร้าย (Malicious Clients) 2 เครื่อง
print("☠️ กำลังรันโหนดผู้ร้าย (Malicious Clients) 2 เครื่อง...")
for i in range(2):
    proc = subprocess.Popen(
        ["python", "malicious_client.py"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    processes.append((f"Malicious-{i+1}", proc))
    time.sleep(0.5)

print("=" * 50)
print("✅ โหนดทั้งหมดกำลังทำงานแล้ว! กำลังรอผลลัพธ์...")
print("💡 กด Ctrl+C เพื่อหยุดการทำงานทั้งหมด")
print("=" * 50)

try:
    # แสดง output จาก Server แบบ real-time
    for name, proc in processes:
        if name == "Server":
            for line in proc.stdout:
                print(f"[{name}] {line}", end='')
                sys.stdout.flush()
    
    # รอให้ทุกกระบวนการจบ
    for name, proc in processes:
        proc.wait()
except KeyboardInterrupt:
    print("\n🛑 กำลังหยุดการทำงานทั้งหมด...")
    for name, proc in processes:
        proc.terminate()
    print("✅ หยุดการทำงานเรียบร้อย")
