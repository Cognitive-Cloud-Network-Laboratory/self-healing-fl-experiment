#!/bin/bash
cd /root/fl-project
source .venv/bin/activate

echo "🛡️ กำลังรัน Benign Clients 8 เครื่อง..."
for i in $(seq 1 8); do
    python -u client.py > /tmp/client_benign_${i}.log 2>&1 &
    echo "  Benign Client $i started (PID: $!)"
    sleep 0.5
done

echo "☠️ กำลังรัน Malicious Clients 2 เครื่อง..."
for i in $(seq 1 2); do
    python -u malicious_client.py > /tmp/client_malicious_${i}.log 2>&1 &
    echo "  Malicious Client $i started (PID: $!)"
    sleep 0.5
done

echo ""
echo "✅ Clients ทั้งหมด 10 เครื่องกำลังทำงานแล้ว!"
echo "💡 รอการเทรนเสร็จ..."
wait
