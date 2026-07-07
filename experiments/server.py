import flwr as fl
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Tuple, Union, Optional
from flwr.common import Parameters, FitRes, EvaluateRes
from flwr.server.client_proxy import ClientProxy
import hashlib
import json
import os
import time
import csv

# ==========================================
# 1. โครงสร้างโมเดล (ต้องเหมือนกับฝั่ง Client ทุกประการ)
# ==========================================
class SimpleCNN(nn.Module):
    def __init__(self):
        super(SimpleCNN, self).__init__()
        self.conv1 = nn.Conv2d(3, 6, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16 * 5 * 5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x

# ==========================================
# 1b. คลาสสมุดบัญชีแยกประเภท (Local Ledger)
# ==========================================
class LocalLedger:
    def __init__(self):
        self.chain = [] # เก็บประวัติเป็น List 
        self.ledger_file = "ledger_history.json" # ไฟล์สำหรับเซฟประวัติลงเครื่อง

    def add_record(self, round_num, accuracy, file_path):
        # 1. ตรวจสอบว่ามีไฟล์น้ำหนัก (.pth) อยู่จริงหรือไม่
        if not os.path.exists(file_path):
            print(f"❌ ไม่พบไฟล์ {file_path}")
            return

        # 2. อ่านไฟล์และสร้าง Hash (SHA-256)
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        # 3. สร้าง Block ข้อมูล
        record = {
            "round": round_num,
            "accuracy": round(accuracy, 4), # ปัดทศนิยม 4 ตำแหน่ง
            "model_hash": file_hash,
            "file_path": file_path
        }
        self.chain.append(record)
        print(f"🔗 [Ledger] บันทึกลงบัญชีสำเร็จ: Round {round_num} | Acc: {accuracy:.4f} | Hash: {file_hash[:8]}...")

        # 4. เซฟลงไฟล์ JSON ให้เป็นเหมือน Database
        with open(self.ledger_file, "w") as f:
            json.dump(self.chain, f, indent=4)

    def get_latest_safe_record(self):
        """ดึงประวัติ Snapshot ล่าสุดที่ปลอดภัย (Record สุดท้ายในลิสต์)"""
        if len(self.chain) == 0:
            return None
        return self.chain[-1] 

    def verify_attestation(self, record):
        """ตรวจสอบความถูกต้องของไฟล์ (Attestation) ด้วย SHA-256"""
        file_path = record["file_path"]
        expected_hash = record["model_hash"]
        
        if not os.path.exists(file_path):
            print(f"❌ [Attestation Failed] ไม่พบไฟล์ {file_path}")
            return False
            
        # อ่านไฟล์ปัจจุบันแล้ว Hash ใหม่
        with open(file_path, "rb") as f:
            current_hash = hashlib.sha256(f.read()).hexdigest()
            
        if current_hash == expected_hash:
            print(f"✅ [Attestation Passed] ไฟล์ถูกต้อง Hash ตรงกัน: {current_hash[:8]}...")
            return True
        else:
            print(f"❌ [Attestation Failed] ไฟล์ถูกดัดแปลง! Hash ไม่ตรงกัน!")
            return False

# ==========================================
# 2. Custom Strategy (ระบบ Self-Healing ฉบับสมบูรณ์ + เก็บสถิติ Evaluation)
# ==========================================
class SaveModelStrategy(fl.server.strategy.FedAvg):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = LocalLedger()
        self.best_accuracy = 0.0
        
        # ตัวแปรสำหรับควบคุมการ Rollback
        self.rollback_mode = False
        self.safe_parameters = None 
        
        # 🟢 [METRICS] 1. เตรียมไฟล์ CSV สำหรับเก็บประวัติ
        self.csv_file = "evaluation_metrics.csv"
        # สร้างหัวตาราง (Header) หากยังไม่มีไฟล์
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    # --- 1. ขั้นตอนก่อนเริ่มเทรน: ส่งน้ำหนักไปให้ Client ---
    def configure_fit(self, server_round: int, parameters: Parameters, client_manager):
        # 🟢 กระบวนการ ROLLBACK ทำงานตรงนี้!
        if self.rollback_mode and (self.safe_parameters is not None):
            print(f"🔄 [ROLLBACK INITIATED] ยกเลิกน้ำหนักที่พัง โหลดน้ำหนักจาก Ledger สำหรับ Round {server_round}")
            parameters = self.safe_parameters # สับเปลี่ยนน้ำหนักเป็นตัวที่ปลอดภัย
            self.rollback_mode = False        # รีเซ็ตสถานะ
            
        return super().configure_fit(server_round, parameters, client_manager)

    # --- 2. ขั้นตอนรับน้ำหนักหลังเทรน (เหมือนเดิม) ---
    def aggregate_fit(self, server_round, results, failures):
        aggregated_parameters, aggregated_metrics = super().aggregate_fit(server_round, results, failures)
        
        if aggregated_parameters is not None:
            aggregated_ndarrays = fl.common.parameters_to_ndarrays(aggregated_parameters)
            net = SimpleCNN()
            params_dict = zip(net.state_dict().keys(), aggregated_ndarrays)
            state_dict = {k: torch.tensor(v) for k, v in params_dict}
            net.load_state_dict(state_dict, strict=True)

            filename = f"global_model_round_{server_round}.pth"
            torch.save(net.state_dict(), filename)
            print(f"💾 [Snapshot] บันทึกโมเดลชั่วคราว: {filename}")

        return aggregated_parameters, aggregated_metrics

    # --- 3. ขั้นตอนประเมินผล: ดักจับและสั่ง Rollback ---
    def aggregate_evaluate(self, server_round, results, failures):
        loss, metrics = super().aggregate_evaluate(server_round, results, failures)
        if not results:
            return loss, metrics

        # คำนวณ Accuracy เฉลี่ย
        total_examples = sum([res.num_examples for _, res in results])
        weighted_acc = sum([res.metrics["accuracy"] * res.num_examples for _, res in results])
        current_accuracy = weighted_acc / total_examples

        print(f"\n📊 ผลการประเมิน Round {server_round} - Accuracy: {current_accuracy:.4f}")

        # 🟢 [METRICS] 2. ตัวแปรเก็บสถานะเพื่อลง CSV
        event_status = "Normal"
        recovery_latency = 0.0

        # 🟢 เงื่อนไขดักจับ (THRESHOLD LOGIC) : Acc ลดลง 10% (0.10)
        if current_accuracy < (self.best_accuracy - 0.10):
            print("==================================================")
            print("🚨 [CRITICAL ALERT] ตรวจพบ DATA POISONING รุนแรง! Accuracy ดิ่งลง!")
            print(f" ก่อนหน้า: {self.best_accuracy:.4f} | ปัจจุบัน: {current_accuracy:.4f}")
            print("==================================================")
            event_status = "Poisoning Detected & Rollback"
            
            # 🟢 [METRICS] 3. เริ่มจับเวลา (Start Timer)
            start_time = time.time()
            
            # เริ่มกระบวนการ Rollback (ระงับการเซฟ, ค้นหาไฟล์เก่า)
            record = self.ledger.get_latest_safe_record()
            
            if record and self.ledger.verify_attestation(record):
                print(f"🛡️ โหลด Snapshot ที่ปลอดภัยจาก Round {record['round']}")
                
                # โหลด .pth กลับมาเป็น Parameters ของ Flower
                net = SimpleCNN()
                net.load_state_dict(torch.load(record["file_path"]))
                safe_ndarrays = [val.cpu().numpy() for _, val in net.state_dict().items()]
                
                self.safe_parameters = fl.common.ndarrays_to_parameters(safe_ndarrays)
                self.rollback_mode = True # สั่งให้รอบถัดไปทำ Rollback
            else:
                event_status = "Rollback Failed"
                print("❌ ไม่พบ Snapshot ที่ปลอดภัย หรือ Attestation ล้มเหลว ระบบไม่สามารถรักษาตัวเองได้!")

            # 🟢 [METRICS] 4. หยุดจับเวลาและคำนวณเป็นมิลลิวินาที (ms)
            end_time = time.time()
            recovery_latency = (end_time - start_time) * 1000
            print(f"⏱️ [EVALUATION] Recovery Latency: {recovery_latency:.2f} ms")
            
        else:
            # สถานการณ์ปกติ -> บันทึกลง Ledger
            print(f"✅ สถานะปกติ บันทึก Round {server_round} เป็นจุดเซฟที่ปลอดภัย")
            file_path = f"global_model_round_{server_round}.pth"
            self.ledger.add_record(server_round, current_accuracy, file_path)
            
            if current_accuracy > self.best_accuracy:
                self.best_accuracy = current_accuracy
                event_status = "New Best Model"

        # 🟢 [METRICS] 5. บันทึกข้อมูลของรอบนี้ลงไฟล์ CSV
        with open(self.csv_file, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([server_round, round(current_accuracy, 4), event_status, round(recovery_latency, 2)])
            print(f"📈 [EVALUATION] บันทึกสถิติ Round {server_round} ลง CSV เรียบร้อย")

        print("\n")
        return loss, {"accuracy": current_accuracy}

# ==========================================
# 3. เริ่มทำงาน (Start Server)
# ==========================================
# ใช้ SaveModelStrategy แทน FedAvg แบบเดิม
strategy = SaveModelStrategy(
    fraction_fit=1.0,         
    fraction_evaluate=1.0,    
    min_fit_clients=10,        
    min_evaluate_clients=10,   
    min_available_clients=10,  
)

if __name__ == "__main__":
    print("🌐 เริ่มต้นโหนดแม่ (Server) พร้อมระบบ Self-Healing... กำลังรอโหนดเชื่อมต่อ 10 เครื่อง")
    fl.server.start_server(
        server_address="0.0.0.0:9090",
        config=fl.server.ServerConfig(num_rounds=5), # เทรน 5 รอบ
        strategy=strategy,
    )
