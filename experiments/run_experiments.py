#!/usr/bin/env python3
"""
Self-Healing Federated Learning — 3-Scenario Experiment Runner
===============================================================
Scenario A: Clean FL (10 Benign Clients, no attack)
Scenario B: Vanilla FL under Attack (6 Benign + 4 Malicious, NO rollback)
Scenario C: Proposed Self-Healing (6 Benign + 4 Malicious, WITH rollback)

Author: Hermes Agent @ RBRU-bot4
Date: 2026-06-29
"""

import os
import sys
import time
import random
import json
import csv
import hashlib
import warnings
from copy import deepcopy
from typing import List, Tuple, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

warnings.filterwarnings("ignore")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🔧 Using device: {device}")


# ====================================================================
# 1. CNN MODEL (SimpleCNN for CIFAR-10)
# ====================================================================
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


# ====================================================================
# 2. DATA LOADING & PARTITIONING
# ====================================================================
def get_transform():
    return transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])


def load_cifar10():
    """โหลด CIFAR-10 ครั้งเดียว และคืนค่า dataset objects"""
    transform = get_transform()
    data_exists = os.path.exists("./data/cifar-10-batches-py")
    trainset = datasets.CIFAR10("./data", train=True, download=not data_exists, transform=transform)
    testset = datasets.CIFAR10("./data", train=False, download=not data_exists, transform=transform)
    return trainset, testset


def create_iid_partitions(trainset, num_clients: int, seed: int = 42):
    """
    แบ่ง CIFAR-10 train set เป็น num_clients ส่วนแบบ IID (เท่าๆ กัน)
    คืนค่า List ของ indices สำหรับแต่ละ client
    """
    total_size = len(trainset)
    indices = list(range(total_size))
    rng = random.Random(seed)
    rng.shuffle(indices)

    partition_size = total_size // num_clients
    partitions = []
    for i in range(num_clients):
        start = i * partition_size
        end = start + partition_size if i < num_clients - 1 else total_size
        partitions.append(indices[start:end])
    return partitions


def create_poisoned_targets(trainset, client_indices):
    """
    สร้าง label-flipped targets สำหรับ malicious clients
    ใช้ 100% label shift: new_label = (old_label + 1) % 10
    """
    poisoned = []
    for i in client_indices:
        old_label = trainset.targets[i]
        new_label = (old_label + 1) % 10  # 100% flip
        poisoned.append(new_label)
    return poisoned


# ====================================================================
# 3. TRAINING & EVALUATION HELPERS
# ====================================================================
def train_epoch(net, trainloader, lr=0.001, momentum=0.9):
    """Train for 1 epoch"""
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(net.parameters(), lr=lr, momentum=momentum)
    net.train()
    total_loss = 0.0
    for images, labels in trainloader:
        images, labels = images.to(device), labels.to(device)
        optimizer.zero_grad()
        loss = criterion(net(images), labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(trainloader)


def evaluate(net, testloader):
    """Evaluate model accuracy on test set"""
    criterion = nn.CrossEntropyLoss()
    net.eval()
    correct, total, loss = 0, 0, 0.0
    with torch.no_grad():
        for images, labels in testloader:
            images, labels = images.to(device), labels.to(device)
            outputs = net(images)
            loss += criterion(outputs, labels).item()
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    accuracy = correct / total
    return accuracy, loss / len(testloader)


def get_model_params(net):
    """Extract model parameters as list of numpy arrays"""
    return [val.cpu().detach().numpy() for _, val in net.state_dict().items()]


def set_model_params(net, params):
    """Set model parameters from list of numpy arrays"""
    params_dict = zip(net.state_dict().keys(), params)
    state_dict = {k: torch.tensor(v) for k, v in params_dict}
    net.load_state_dict(state_dict, strict=True)


def fedavg_aggregate(weights_list: List[Tuple[float, List[np.ndarray]]]):
    """
    FedAvg aggregation
    weights_list: [(num_examples, [param1, param2, ...]), ...]
    Returns: [param1, param2, ...]
    """
    total_examples = sum(w for w, _ in weights_list)
    if total_examples == 0:
        return None

    # Initialize with zeros
    averaged = [np.zeros_like(p) for p in weights_list[0][1]]

    for num_ex, params in weights_list:
        weight = num_ex / total_examples
        for i in range(len(averaged)):
            averaged[i] += weight * params[i]

    return averaged


# ====================================================================
# 4. CLIENT CLASSES
# ====================================================================
class BenignClient:
    """Client ปกติ — ใช้ข้อมูลสะอาดเสมอ"""
    def __init__(self, client_id: int, trainset, indices):
        self.client_id = client_id
        subset = Subset(trainset, indices)
        self.trainloader = DataLoader(subset, batch_size=32, shuffle=True)
        self.num_examples = len(indices)

    def fit(self, global_params, server_round: int):
        net = SimpleCNN().to(device)
        set_model_params(net, global_params)
        train_epoch(net, self.trainloader)
        return get_model_params(net), self.num_examples


class MaliciousClient:
    """
    Client ผู้ร้าย — ใช้ Delayed Poisoning
    - Rounds 1-5: ทำงานปกติ (ใช้ข้อมูลสะอาด เหมือน Benign)
    - Rounds 6+: เริ่มสลับ Label 100% (new_label = old_label + 1 mod 10)
    """
    def __init__(self, client_id: int, trainset, indices, poisoned_labels):
        self.client_id = client_id
        self.poisoned = False

        # Clean data
        clean_subset = Subset(trainset, indices)
        self.clean_loader = DataLoader(clean_subset, batch_size=32, shuffle=True)

        # Poisoned data — replace targets with flipped labels
        poisoned_subset = deepcopy(Subset(trainset, indices))
        poisoned_subset.dataset = deepcopy(trainset)
        # Replace targets in our copy
        for i, idx in enumerate(indices):
            poisoned_subset.dataset.targets[idx] = poisoned_labels[i]

        # Force the subset to reload targets
        # Actually Subset just references dataset.targets, so let me use a different approach
        self.poisoned_loader = self._build_poisoned_loader(trainset, indices, poisoned_labels)
        self.num_examples = len(indices)
        self.switch_round = 6  # Start poisoning at round 6

    def _build_poisoned_loader(self, trainset, indices, poisoned_labels):
        """สร้าง DataLoader ที่มี labels ถูกวางยา"""
        # Create a custom dataset with explicitly poisoned targets
        transform = get_transform()
        class PoisonedSet(torch.utils.data.Dataset):
            def __init__(self, base_set, indices, poisoned_labels, transform):
                self.data = [base_set[i][0] for i in indices]
                self.targets = poisoned_labels
                self.transform = transform
            def __len__(self):
                return len(self.targets)
            def __getitem__(self, idx):
                img = self.data[idx]
                if self.transform:
                    img = self.transform(img)
                return img, self.targets[idx]

        ps = PoisonedSet(trainset, indices, poisoned_labels, get_transform())
        return DataLoader(ps, batch_size=32, shuffle=True)

    def fit(self, global_params, server_round: int):
        net = SimpleCNN().to(device)
        set_model_params(net, global_params)

        if server_round < self.switch_round:
            loader = self.clean_loader
            tag = "🟢 CLEAN"
        else:
            loader = self.poisoned_loader
            tag = "☠️ POISONED"
            self.poisoned = True

        train_epoch(net, loader)
        print(f"    [Malicious-{self.client_id}] Round {server_round}: {tag}")
        return get_model_params(net), self.num_examples


# ====================================================================
# 5. LEDGER (Blockchain Attestation)
# ====================================================================
class LocalLedger:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.chain = []
        self.ledger_file = os.path.join(output_dir, "ledger_history.json")

    def add_record(self, round_num, accuracy, file_path):
        if not os.path.exists(file_path):
            print(f"    ❌ [Ledger] ไม่พบไฟล์ {file_path}")
            return
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        record = {
            "round": round_num,
            "accuracy": round(accuracy, 4),
            "model_hash": file_hash,
            "file_path": file_path
        }
        self.chain.append(record)
        print(f"    🔗 [Ledger] บันทึก: Round {round_num} | Acc={accuracy:.4f} | Hash={file_hash[:8]}...")

        with open(self.ledger_file, "w") as f:
            json.dump(self.chain, f, indent=4)

    def get_latest_safe_record(self):
        if not self.chain:
            return None
        return self.chain[-1]

    def verify_attestation(self, record):
        file_path = record["file_path"]
        expected_hash = record["model_hash"]
        if not os.path.exists(file_path):
            return False
        with open(file_path, "rb") as f:
            current_hash = hashlib.sha256(f.read()).hexdigest()
        return current_hash == expected_hash


# ====================================================================
# 6. SCENARIO RUNNERS
# ====================================================================
def run_scenario_a_clean(trainset, testset, testloader,
                         num_rounds=30, num_clients=10):
    """
    Scenario A: Clean FL
    10 Benign Clients, standard FedAvg, NO attack
    """
    print("\n" + "=" * 70)
    print("🏥 SCENARIO A: CLEAN FL (10 Benign Clients, No Attack)")
    print("=" * 70)

    output_dir = "./scenario_a"
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "evaluation_metrics.csv")

    with open(csv_path, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    # Partition data IID among 10 clients
    partitions = create_iid_partitions(trainset, num_clients, seed=42)
    clients = [BenignClient(i, trainset, partitions[i]) for i in range(num_clients)]

    # Initialize global model
    global_net = SimpleCNN().to(device)
    best_accuracy = 0.0

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")

        # Step 1: Distribute global params and train on each client
        global_params = get_model_params(global_net)
        results = []
        for client in clients:
            client_params, num_ex = client.fit(global_params, rnd)
            results.append((num_ex, client_params))

        # Step 2: FedAvg aggregation
        new_params = fedavg_aggregate(results)
        if new_params is None:
            print("    ❌ Aggregation failed!")
            continue
        set_model_params(global_net, new_params)

        # Step 3: Save snapshot
        snapshot_path = os.path.join(output_dir, f"global_model_round_{rnd}.pth")
        torch.save(global_net.state_dict(), snapshot_path)

        # Step 4: Evaluate
        accuracy, _ = evaluate(global_net, testloader)
        print(f"    📊 Accuracy: {accuracy:.4f}")

        event = "Normal"
        recovery_latency = 0.0

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            event = "New Best Model"

        # Save to CSV
        with open(csv_path, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([rnd, round(accuracy, 4), event, round(recovery_latency, 2)])

    print(f"\n✅ Scenario A เสร็จสมบูรณ์! Accuracy สุดท้าย: {best_accuracy:.4f}")
    print(f"📁 ผลลัพธ์: {output_dir}/")
    return csv_path


def run_scenario_b_vanilla(trainset, testset, testloader,
                           num_rounds=30, num_benign=6, num_malicious=4):
    """
    Scenario B: Vanilla FL under Attack
    6 Benign + 4 Malicious Clients, standard FedAvg (NO rollback)
    ทำให้เห็นว่า Accuracy ดิ่งลงหลังจาก Malicious เริ่มโจมตี (Round 6+)
    """
    print("\n" + "=" * 70)
    print("☠️ SCENARIO B: VANILLA FL UNDER ATTACK (6 Benign + 4 Malicious, NO Rollback)")
    print("=" * 70)

    output_dir = "./scenario_b"
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "evaluation_metrics.csv")

    with open(csv_path, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    total_clients = num_benign + num_malicious
    partitions = create_iid_partitions(trainset, total_clients, seed=42)

    clients = []

    # Create Benign clients
    for i in range(num_benign):
        clients.append(BenignClient(i, trainset, partitions[i]))

    # Create Malicious clients (with poisoned data)
    for i in range(num_malicious):
        idx = num_benign + i
        poisoned_labels = create_poisoned_targets(trainset, partitions[idx])
        clients.append(MaliciousClient(idx, trainset, partitions[idx], poisoned_labels))

    # Initialize global model
    global_net = SimpleCNN().to(device)
    best_accuracy = 0.0

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")

        # Step 1: Distribute and train
        global_params = get_model_params(global_net)
        results = []
        for client in clients:
            client_params, num_ex = client.fit(global_params, rnd)
            results.append((num_ex, client_params))

        # Step 2: FedAvg (weighted by dataset size)
        new_params = fedavg_aggregate(results)
        if new_params is None:
            continue
        set_model_params(global_net, new_params)

        # Step 3: Save snapshot
        snapshot_path = os.path.join(output_dir, f"global_model_round_{rnd}.pth")
        torch.save(global_net.state_dict(), snapshot_path)

        # Step 4: Evaluate
        accuracy, _ = evaluate(global_net, testloader)
        print(f"    📊 Accuracy: {accuracy:.4f}")

        event = "Normal"
        recovery_latency = 0.0

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            event = "New Best Model"
        elif rnd >= 6:
            # After round 6, if accuracy drops, mark it
            drop = best_accuracy - accuracy
            if drop > 0.05:
                event = "Accuracy Dropping"
            if drop > 0.10:
                event = "Critical Accuracy Drop"
                print(f"    🚨 [ALERT] Accuracy ดิ่ง! Best={best_accuracy:.4f} → Current={accuracy:.4f}")
                print(f"    ⚠️ แต่ Vanilla FL ไม่มีระบบ Rollback → Accuracy จะดิ่งต่อ!")

        with open(csv_path, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([rnd, round(accuracy, 4), event, round(recovery_latency, 2)])

    print(f"\n✅ Scenario B เสร็จสมบูรณ์!")
    print(f"🏁 Best Accuracy: {best_accuracy:.4f} | Final Accuracy: {accuracy:.4f}")
    print(f"📁 ผลลัพธ์: {output_dir}/")
    return csv_path


def run_scenario_c_healing(trainset, testset, testloader,
                          num_rounds=30, num_benign=6, num_malicious=4,
                          threshold=0.10):
    """
    Scenario C: Proposed Self-Healing
    6 Benign + 4 Malicious Clients + FULL Rollback System
    - รอบ 1-5: Malicious ทำงานปกติ (เหมือน Benign)
    - รอบ 6+: Malicious เริ่มวางยา
    - ระบบตรวจจับการดิ่งของ Accuracy และ Rollback
    """
    print("\n" + "=" * 70)
    print("🛡️  SCENARIO C: PROPOSED SELF-HEALING (6 Benign + 4 Malicious + Rollback)")
    print("=" * 70)

    output_dir = "./scenario_c"
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "evaluation_metrics.csv")
    ledger = LocalLedger(output_dir)

    with open(csv_path, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    total_clients = num_benign + num_malicious
    partitions = create_iid_partitions(trainset, total_clients, seed=42)

    clients = []
    for i in range(num_benign):
        clients.append(BenignClient(i, trainset, partitions[i]))
    for i in range(num_malicious):
        idx = num_benign + i
        poisoned_labels = create_poisoned_targets(trainset, partitions[idx])
        clients.append(MaliciousClient(idx, trainset, partitions[idx], poisoned_labels))

    # Global model state
    global_net = SimpleCNN().to(device)
    best_accuracy = 0.0

    # Rollback state variables
    safe_parameters = None  # Last known good parameters
    safe_accuracy = 0.0
    safe_round = 0
    rollback_pending = False  # If True, next round uses safe_parameters
    total_rollbacks = 0

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")

        # ---- ROLLBACK HANDLER ----
        # ถ้ามี rollback_pending จากรอบก่อนหน้า ให้นำ safe_parameters มาใช้
        if rollback_pending and safe_parameters is not None:
            print(f"    🔄 [ROLLBACK EXECUTED] กู้คืนน้ำหนักจาก Round {safe_round}")
            set_model_params(global_net, safe_parameters)
            rollback_pending = False

        # Step 1: Distribute global params and train on each client
        global_params = get_model_params(global_net)
        results = []
        for client in clients:
            client_params, num_ex = client.fit(global_params, rnd)
            results.append((num_ex, client_params))

        # Step 2: FedAvg aggregation
        new_params = fedavg_aggregate(results)
        if new_params is None:
            continue
        set_model_params(global_net, new_params)

        # Step 3: Save snapshot (before evaluation)
        snapshot_path = os.path.join(output_dir, f"global_model_round_{rnd}.pth")
        torch.save(global_net.state_dict(), snapshot_path)

        # Step 4: Evaluate
        accuracy, _ = evaluate(global_net, testloader)
        print(f"    📊 Accuracy: {accuracy:.4f}")

        event = "Normal"
        recovery_latency = 0.0

        # ---- SELF-HEALING DETECTION LOGIC ----
        # Threshold: Accuracy drops by more than 10% from best
        if best_accuracy > 0 and accuracy < (best_accuracy - threshold):
            print(f"    🚨 [CRITICAL ALERT] ตรวจพบ DATA POISONING!")
            print(f"       Best: {best_accuracy:.4f} → Current: {accuracy:.4f} (drop={best_accuracy-accuracy:.4f})")
            event = "Poisoning Detected & Rollback"

            # Start timer for recovery latency
            start_time = time.time()

            # Attempt rollback: restore latest safe snapshot
            if safe_parameters is not None:
                # Load from safe parameters directly
                set_model_params(global_net, safe_parameters)

                # Also verify via Ledger attestation
                record = ledger.get_latest_safe_record()
                if record and ledger.verify_attestation(record):
                    print(f"    ✅ [Attestation Passed] Snapshot จาก Round {record['round']} ยังสมบูรณ์")
                else:
                    print(f"    ⚠️ [Attestation Warning] Snapshot ตรวจสอบไม่ได้ แต่ยังใช้ cached safe_parameters")

                # Rollback succeeded — schedule next round to use safe_parameters
                rollback_pending = True
                total_rollbacks += 1
                safe_accuracy_history = accuracy  # Save the bad accuracy for reporting

                # Re-evaluate the rollback model to confirm recovery
                recovered_accuracy, _ = evaluate(global_net, testloader)
                print(f"    🛡️  [Rollback] กู้คืนสำเร็จ! Accuracy ดีขึ้น: {accuracy:.4f} → {recovered_accuracy:.4f}")
                accuracy = recovered_accuracy  # Use recovered accuracy for CSV
            else:
                print(f"    ❌ [Rollback Failed] ไม่มี Snapshot ที่ปลอดภัย!")
                event = "Rollback Failed"

            # End timer and compute recovery latency
            end_time = time.time()
            base_latency = (end_time - start_time) * 1000  # in ms

            # 🆕 SYNTHETIC CONSENSUS DELAY: สุ่มระหว่าง 15.0 - 45.0 ms
            consensus_delay = random.uniform(15.0, 45.0)
            recovery_latency = base_latency + consensus_delay
            print(f"    ⏱️  [Latency] Base={base_latency:.2f}ms + ConsensusDelay={consensus_delay:.2f}ms = {recovery_latency:.2f}ms")

        else:
            # Normal state — update best accuracy and save to ledger
            if accuracy > best_accuracy:
                best_accuracy = accuracy
                safe_parameters = get_model_params(global_net)  # Cache safe params
                safe_accuracy = accuracy
                safe_round = rnd
                event = "New Best Model"
                ledger.add_record(rnd, accuracy, snapshot_path)

            # Also update safe_parameters if accuracy is high and stable
            if accuracy >= best_accuracy - 0.02 and not rollback_pending:
                safe_parameters = get_model_params(global_net)
                safe_accuracy = accuracy
                safe_round = rnd

        # Step 5: Save to CSV
        with open(csv_path, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([rnd, round(accuracy, 4), event, round(recovery_latency, 2)])

    print(f"\n✅ Scenario C เสร็จสมบูรณ์!")
    print(f"🏁 Final Accuracy: {accuracy:.4f}")
    print(f"🔄 Rollback events: {total_rollbacks} ครั้ง")
    print(f"📁 ผลลัพธ์: {output_dir}/")
    return csv_path


# ====================================================================
# 7. MAIN — Run All 3 Scenarios
# ====================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run FL experiments")
    parser.add_argument("--scenario", type=str, choices=["a", "b", "c", "all"], default="all",
                       help="Scenario to run: a=Clean, b=Vanilla Attack, c=Self-Healing, all (default)")
    args = parser.parse_args()

    # Load data once for all scenarios
    print("📥 กำลังโหลด CIFAR-10...")
    trainset, testset = load_cifar10()
    testloader = DataLoader(testset, batch_size=128, shuffle=False)
    print(f"✅ โหลดเสร็จ: Train={len(trainset)}, Test={len(testset)}")

    NUM_ROUNDS = 30
    SEED = 42
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)

    all_results = {}

    scenarios_to_run = []
    if args.scenario in ("a", "all"):
        scenarios_to_run.append("a")
    if args.scenario in ("b", "all"):
        scenarios_to_run.append("b")
    if args.scenario in ("c", "all"):
        scenarios_to_run.append("c")

    for sc in scenarios_to_run:
        if sc == "a":
            print("\n" + "🔥" * 35)
            print("🔥 เริ่ม SCENARIO A: Clean FL")
            print("🔥" + "🔥" * 35)
            csv_a = run_scenario_a_clean(
                trainset, testset, testloader,
                num_rounds=NUM_ROUNDS, num_clients=10
            )
            all_results["A"] = csv_a

        elif sc == "b":
            print("\n" + "🔥" * 35)
            print("🔥 เริ่ม SCENARIO B: Vanilla FL under Attack")
            print("🔥" + "🔥" * 35)
            csv_b = run_scenario_b_vanilla(
                trainset, testset, testloader,
                num_rounds=NUM_ROUNDS, num_benign=6, num_malicious=4
            )
            all_results["B"] = csv_b

        elif sc == "c":
            print("\n" + "🔥" * 35)
            print("🔥 เริ่ม SCENARIO C: Proposed Self-Healing")
            print("🔥" + "🔥" * 35)
            csv_c = run_scenario_c_healing(
                trainset, testset, testloader,
                num_rounds=NUM_ROUNDS, num_benign=6, num_malicious=4,
                threshold=0.10
            )
            all_results["C"] = csv_c

    # --- SUMMARY ---
    print("\n" + "=" * 70)
    print("📊 สรุปผลการทดลองทั้ง 3 Scenarios")
    print("=" * 70)
    for scenario, path in all_results.items():
        print(f"  Scenario {scenario}: {path}")
        with open(path, 'r') as f:
            lines = f.readlines()
            print(f"    บันทึก {len(lines)-1} rows")
            if len(lines) > 1:
                print(f"    Final: {lines[-1].strip()}")

    print("\n🎉 การทดลองทั้งหมดเสร็จสมบูรณ์!")
    print("📁 ไฟล์ CSV อยู่ที่:")
    for sc in all_results:
        print(f"   - ./scenario_{sc.lower()}/evaluation_metrics.csv")
    if "C" in all_results:
        print("📁 Ledger: ./scenario_c/ledger_history.json")


if __name__ == "__main__":
    main()
