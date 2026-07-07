#!/bin/bash
# Self-Healing Federated Learning Runner
# ใช้สคริปต์นี้แทน run_simulation.py เพื่อความเสถียร

set -e

cd "$(dirname "$0")"
source .venv/bin/activate

echo "🟢 เตรียมข้อมูล CIFAR-10..."
python -c "
import os, sys
# ตรวจสอบว่ามีข้อมูลอยู่แล้ว
data_dir = './data/cifar-10-batches-py'
if os.path.exists(data_dir) and len(os.listdir(data_dir)) > 5:
    print('✅ พบข้อมูล CIFAR-10 อยู่แล้ว')
else:
    print('📥 กำลังดาวน์โหลด CIFAR-10...')
    from torchvision import datasets, transforms
    transform = transforms.Compose([transforms.ToTensor()])
    trainset = datasets.CIFAR10('./data', train=True, download=True, transform=transform)
    testset = datasets.CIFAR10('./data', train=False, download=True, transform=transform)
    print(f'✅ ดาวน์โหลดเสร็จ: Train={len(trainset)}, Test={len(testset)}')
"
echo ""

SERVER_LOG="/tmp/fl_server.log"
> "$SERVER_LOG"

echo "🌐 กำลังรัน Server บนพอร์ต 9090..."
python -u server.py > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
sleep 5

# ตรวจสอบว่า Server ทำงาน
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "❌ Server ไม่สามารถเริ่มทำงานได้!"
    cat "$SERVER_LOG"
    exit 1
fi
echo "   Server PID: $SERVER_PID (กำลังรอ Clients 10 เครื่อง)"
echo ""

# เปิด Clients แบบมีระยะห่าง
echo "🛡️ กำลังรัน Benign Clients 8 เครื่อง..."
BENIGN_PIDS=""
for i in $(seq 1 8); do
    CLIENT_LOG="/tmp/fl_client_b_${i}.log"
    python -u client.py > "$CLIENT_LOG" 2>&1 &
    CLIENT_PID=$!
    BENIGN_PIDS="$BENIGN_PIDS $CLIENT_PID"
    echo "   Benign $i started (PID: $CLIENT_PID)"
    sleep 1  # เว้นระยะให้แต่ละตัวโหลดข้อมูล
done
echo ""

# Malicious Clients
echo "☠️ กำลังรัน Malicious Clients 2 เครื่อง..."
MAL_PIDS=""
for i in $(seq 1 2); do
    CLIENT_LOG="/tmp/fl_client_m_${i}.log"
    python -u malicious_client.py > "$CLIENT_LOG" 2>&1 &
    CLIENT_PID=$!
    MAL_PIDS="$MAL_PIDS $CLIENT_PID"
    echo "   Malicious $i started (PID: $CLIENT_PID)"
    sleep 1
done
echo ""

echo "=" 30
echo "✅ Clients 10 เครื่องกำลังทำงานแล้ว!"
echo "📋 ดู log Server: tail -f $SERVER_LOG"
echo "📋 ดู log Client: tail -f /tmp/fl_client_b_1.log"
echo "💡 กด Ctrl+C เพื่อหยุดทั้งหมด"
echo "=" 30

# ติดตาม Server จนกว่าจะจบ
wait $SERVER_PID 2>/dev/null
echo ""
echo "🏁 Server จบการทำงานแล้ว!"
echo "📊 ดูผลลัพธ์:"
echo "   - ledger_history.json (บันทึก Blockchain)"
echo "   - evaluation_metrics.csv (สถิติ)"
echo "   - global_model_round_*.pth (Snapshots)"

# หยุด Clients ที่เหลือ
echo "🛑 กำลังหยุด Clients..."
kill $BENIGN_PIDS $MAL_PIDS 2>/dev/null
echo "✅ เสร็จสิ้น"
