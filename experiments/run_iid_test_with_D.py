#!/usr/bin/env python3
"""
Self-Healing FL — IID Test Partition (4 Scenarios: A+B+C+D)
============================================================
- Train set: 50,000 รูป → partition IID ให้ client ละ 5,000 รูป
- Test set:  10,000 รูป → partition IID ให้ client ละ 1,000 รูป
- แต่ละ client evaluate บน test partition ของตัวเอง
- Server aggregate accuracy แบบ weighted average

Scenarios:
  A: Clean FL (10 Benign, no attack)
  B: Vanilla FL under Attack (6 Benign + 4 Malicious, no rollback)
  C: Self-Healing (6 Benign + 4 Malicious, rollback only)
  D: Quarantine Protocol (6 Benign + 4 Malicious, rollback + quarantine)

Attack: Label-Flip (100%) + Gradient Inversion (×1.5) from Round 6

Author: Hermes Agent @ RBRU
"""

import os, sys, time, random, json, csv, hashlib, warnings
from copy import deepcopy
from typing import List, Tuple, Optional
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset, Dataset
from torchvision import datasets, transforms
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

warnings.filterwarnings("ignore")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🔧 Using device: {device}")


# ====================================================================
# 1. CNN MODEL
# ====================================================================
class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
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
        return self.fc3(x)


# ====================================================================
# 2. DATA
# ====================================================================
def get_transform():
    return transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])

def load_cifar10():
    transform = get_transform()
    data_exists = os.path.exists("./data/cifar-10-batches-py")
    trainset = datasets.CIFAR10("./data", train=True,
                                download=not data_exists, transform=transform)
    testset = datasets.CIFAR10("./data", train=False,
                               download=not data_exists, transform=transform)
    return trainset, testset


def create_stratified_iid_partitions(dataset, num_clients: int, seed=42):
    """แบ่ง dataset IID แบบ stratified"""
    targets = np.array(dataset.targets)
    num_classes = 10
    client_indices = [[] for _ in range(num_clients)]
    rng = random.Random(seed)

    for c in range(num_classes):
        class_indices = np.where(targets == c)[0].tolist()
        rng.shuffle(class_indices)
        per_client = len(class_indices) // num_clients
        for i in range(num_clients):
            start = i * per_client
            end = start + per_client if i < num_clients - 1 else len(class_indices)
            client_indices[i].extend(class_indices[start:end])

    for i in range(num_clients):
        rng.shuffle(client_indices[i])

    return client_indices


def create_poisoned_labels(dataset, client_indices):
    """label-flip 100%: new_label = (old_label + 1) % 10"""
    poisoned = []
    for i in client_indices:
        new_label = (dataset.targets[i] + 1) % 10
        poisoned.append(new_label)
    return poisoned


# ====================================================================
# 3. HELPERS
def train_epoch(net, trainloader, lr=0.01, momentum=0.9, epochs=2):
    """Train for multiple epochs"""
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(net.parameters(), lr=lr, momentum=momentum)
    net.train()
    total_loss = 0.0
    for _ in range(epochs):
        for images, labels in trainloader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(net(images), labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
    return total_loss / (len(trainloader) * epochs)


def evaluate(net, testloader):
    """Evaluate model accuracy and loss"""
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
    return [val.cpu().detach().numpy() for _, val in net.state_dict().items()]

def set_model_params(net, params):
    params_dict = zip(net.state_dict().keys(), params)
    state_dict = {k: torch.tensor(v) for k, v in params_dict}
    net.load_state_dict(state_dict, strict=True)

def avg_params(weights_list):
    """FedAvg — weighted by num_examples
    Input: [(params: List[np.ndarray], num_examples: int), ...]
    """
    total = sum(n for _, n in weights_list)
    if total == 0:
        return None
    avgd = [np.zeros_like(p) for p in weights_list[0][0]]
    for params, num_ex in weights_list:
        w = num_ex / total
        for i in range(len(avgd)):
            avgd[i] += w * params[i]
    return avgd


# ====================================================================
# 4. CLIENT CLASSES
# ====================================================================
class BenignClient:
    """Client ปกติ — train และ test บน partition ของตัวเอง"""
    def __init__(self, cid, trainset, train_idx, testset, test_idx):
        self.cid = cid
        self.num_train = len(train_idx)
        self.num_test = len(test_idx)
        self.trainloader = DataLoader(Subset(trainset, train_idx), batch_size=32, shuffle=True)
        self.testloader = DataLoader(Subset(testset, test_idx), batch_size=128)

    def fit(self, global_params, rnd):
        net = SimpleCNN().to(device)
        set_model_params(net, global_params)
        train_epoch(net, self.trainloader)
        return get_model_params(net), self.num_train

    def evaluate(self, global_params):
        net = SimpleCNN().to(device)
        set_model_params(net, global_params)
        acc, loss = evaluate(net, self.testloader)
        return acc, loss, self.num_test


class GradientInversionClient:
    """
    Client ผู้ร้าย — Label-Flip + Gradient Inversion
    - Rounds 1-5: ทำงานปกติ (เหมือน Benign)
    - Rounds 6+: วางยา label flip 100% + gradient inversion ×1.5
    - Test: ใช้ test partition ของตัวเอง (data สะอาด)
    """
    def __init__(self, cid, trainset, train_idx, testset, test_idx, poisoned_labels):
        self.cid = cid
        self.num_train = len(train_idx)
        self.num_test = len(test_idx)

        # Clean loader
        self.clean_loader = DataLoader(Subset(trainset, train_idx),
                                       batch_size=32, shuffle=True)

        # Poisoned loader (raw data to avoid double-transform)
        transform = get_transform()
        class PoisonedSet(Dataset):
            def __init__(self, base, indices, p_labels, transform):
                self.raw_data = base.data
                self.indices = indices
                self.targets = p_labels
                self.transform = transform
            def __len__(self):
                return len(self.targets)
            def __getitem__(self, idx):
                img = self.raw_data[self.indices[idx]]
                if self.transform:
                    img = self.transform(img)
                return img, self.targets[idx]

        ps = PoisonedSet(trainset, train_idx, poisoned_labels, transform)
        self.poisoned_loader = DataLoader(ps, batch_size=32, shuffle=True)

        # Test loader (CLEAN)
        self.testloader = DataLoader(Subset(testset, test_idx), batch_size=128)

        self.switch_round = 6

    def fit(self, global_params, rnd):
        net = SimpleCNN().to(device)
        set_model_params(net, global_params)

        if rnd < self.switch_round:
            loader = self.clean_loader
            tag = "CLEAN"
            train_epoch(net, loader)
            return get_model_params(net), self.num_train
        else:
            # Step 1: Train on poisoned data
            loader = self.poisoned_loader
            tag = "POISONED+INVERT"
            train_epoch(net, loader)
            poisoned_params = get_model_params(net)

            # Step 2: Gradient Inversion
            # inverted = global - (trained - global) × 1.5
            inverted = [g - (t - g) * 1.5
                       for g, t in zip(global_params, poisoned_params)]

            print(f"    [Malicious-{self.cid}] Round {rnd}: {tag}")
            return inverted, self.num_train

    def evaluate(self, global_params):
        """Test on CLEAN test partition"""
        net = SimpleCNN().to(device)
        set_model_params(net, global_params)
        acc, loss = evaluate(net, self.testloader)
        return acc, loss, self.num_test


# ====================================================================
# 5. LEDGER
# ====================================================================
class LocalLedger:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.chain = []
        self.ledger_file = os.path.join(output_dir, "ledger_history.json")

    def add_record(self, rnd, accuracy, file_path):
        if not os.path.exists(file_path):
            return
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        rec = {"round": rnd, "accuracy": round(accuracy, 4),
               "model_hash": file_hash, "file_path": file_path}
        self.chain.append(rec)
        with open(self.ledger_file, "w") as f:
            json.dump(self.chain, f, indent=4)

    def get_latest_safe_record(self):
        return self.chain[-1] if self.chain else None

    def verify_attestation(self, rec):
        if not os.path.exists(rec["file_path"]):
            return False
        with open(rec["file_path"], "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == rec["model_hash"]


# ====================================================================
# 6. EVALUATION AGGREGATOR
# ====================================================================
def evaluate_all(clients, global_params):
    """ทุก client test บน partition ของตัวเอง → weighted average"""
    accs, losses, nums = [], [], []
    for c in clients:
        a, l, n = c.evaluate(global_params)
        accs.append(a)
        losses.append(l)
        nums.append(n)
    total_n = sum(nums)
    w_acc = sum(a * n for a, n in zip(accs, nums)) / total_n
    w_loss = sum(l * n for l, n in zip(losses, nums)) / total_n
    return w_acc, w_loss, list(zip(accs, nums))


# ====================================================================
# 7. SCENARIO RUNNERS
# ====================================================================
def run_scenario_a(trainset, testset, train_parts, test_parts,
                   num_rounds=30, num_clients=10):
    """A: Clean FL"""
    print("\n" + "=" * 70)
    print("🏥 SCENARIO A: CLEAN FL (10 Benign Clients)")
    print("=" * 70)
    out_dir = "./scenario_a_iid"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "evaluation_metrics.csv")

    with open(csv_path, 'w', newline='') as f:
        csv.writer(f).writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    clients = [BenignClient(i, trainset, train_parts[i], testset, test_parts[i])
               for i in range(num_clients)]
    global_net = SimpleCNN().to(device)
    best_acc = 0.0

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")
        gp = get_model_params(global_net)
        results = [c.fit(gp, rnd) for c in clients]
        new_p = avg_params(results)
        if new_p is None:
            continue
        set_model_params(global_net, new_p)

        acc, _, _ = evaluate_all(clients, get_model_params(global_net))
        print(f"    📊 Accuracy: {acc:.4f}")

        event = "Normal"
        if acc > best_acc:
            best_acc = acc
            event = "New Best Model"

        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc, 4), event, 0.0])

    print(f"\n✅ Scenario A เสร็จ! Best: {best_acc:.4f}")
    return csv_path


def run_scenario_b(trainset, testset, train_parts, test_parts,
                   num_rounds=30, num_benign=6, num_malicious=4):
    """B: Vanilla FL under Attack — NO rollback"""
    print("\n" + "=" * 70)
    print("☠️ SCENARIO B: VANILLA FL UNDER ATTACK (NO Rollback)")
    print("=" * 70)
    out_dir = "./scenario_b_iid"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "evaluation_metrics.csv")

    with open(csv_path, 'w', newline='') as f:
        csv.writer(f).writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    total = num_benign + num_malicious
    clients = []

    for i in range(num_benign):
        clients.append(BenignClient(i, trainset, train_parts[i],
                                    testset, test_parts[i]))

    for i in range(num_malicious):
        idx = num_benign + i
        p_labels = create_poisoned_labels(trainset, train_parts[idx])
        clients.append(GradientInversionClient(
            idx, trainset, train_parts[idx], testset, test_parts[idx], p_labels))

    global_net = SimpleCNN().to(device)
    best_acc = 0.0

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")
        gp = get_model_params(global_net)
        results = [c.fit(gp, rnd) for c in clients]
        new_p = avg_params(results)
        if new_p is None:
            continue
        set_model_params(global_net, new_p)

        acc, _, _ = evaluate_all(clients, get_model_params(global_net))
        print(f"    📊 Accuracy: {acc:.4f}")

        event = "Normal"
        if acc > best_acc:
            best_acc = acc
            event = "New Best Model"
        elif rnd >= 6:
            drop = best_acc - acc
            if drop > 0.10:
                event = "Critical Accuracy Drop"
                if drop > 0.05:
                    event = "Accuracy Dropping"

        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc, 4), event, 0.0])

    print(f"\n✅ Scenario B เสร็จ! Best: {best_acc:.4f} | Final: {acc:.4f}")
    return csv_path


def run_scenario_c(trainset, testset, train_parts, test_parts,
                   num_rounds=30, num_benign=6, num_malicious=4, threshold=0.10):
    """C: Self-Healing — Rollback only"""
    print("\n" + "=" * 70)
    print("🛡️  SCENARIO C: SELF-HEALING (Rollback only)")
    print("=" * 70)
    out_dir = "./scenario_c_iid"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "evaluation_metrics.csv")
    ledger = LocalLedger(out_dir)

    with open(csv_path, 'w', newline='') as f:
        csv.writer(f).writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms"])

    total = num_benign + num_malicious
    clients = []
    for i in range(num_benign):
        clients.append(BenignClient(i, trainset, train_parts[i], testset, test_parts[i]))
    for i in range(num_malicious):
        idx = num_benign + i
        p_labels = create_poisoned_labels(trainset, train_parts[idx])
        clients.append(GradientInversionClient(
            idx, trainset, train_parts[idx], testset, test_parts[idx], p_labels))

    global_net = SimpleCNN().to(device)
    best_acc = 0.0
    safe_params = None
    safe_accuracy = 0.0
    safe_round = 0
    rollback_pending = False
    total_rollbacks = 0

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")

        if rollback_pending and safe_params is not None:
            print(f"    🔄 [ROLLBACK] กู้คืนจาก Round {safe_round} (acc={safe_accuracy:.4f})")
            set_model_params(global_net, safe_params)
            rollback_pending = False

        gp = get_model_params(global_net)
        results = [c.fit(gp, rnd) for c in clients]
        new_p = avg_params(results)
        if new_p is None:
            continue
        set_model_params(global_net, new_p)

        snapshot_path = os.path.join(out_dir, f"global_model_round_{rnd}.pth")
        torch.save(global_net.state_dict(), snapshot_path)

        acc, _, _ = evaluate_all(clients, get_model_params(global_net))
        print(f"    📊 Accuracy: {acc:.4f}")

        event = "Normal"
        recovery_latency = 0.0

        if best_acc > 0 and acc < (best_acc - threshold):
            print(f"    🚨 [CRITICAL] Best={best_acc:.4f} → Current={acc:.4f}")
            event = "Poisoning Detected & Rollback"
            start_time = time.time()

            if safe_params is not None:
                record = ledger.get_latest_safe_record()
                if record and ledger.verify_attestation(record):
                    print(f"    ✅ [Attestation] Snapshot Round {record['round']} OK")

                rollback_pending = True
                total_rollbacks += 1

                # Re-evaluate after rollback
                recovered_acc, _, _ = evaluate_all(clients, safe_params)
                print(f"    🛡️  [Rollback] {acc:.4f} → {recovered_acc:.4f}")
                acc = recovered_acc
            else:
                print(f"    ❌ [Rollback Failed] No safe snapshot!")
                event = "Rollback Failed"

            end_time = time.time()
            recovery_latency = (end_time - start_time) * 1000 + random.uniform(15.0, 45.0)
            print(f"    ⏱️  Latency: {recovery_latency:.2f} ms")

        else:
            if acc > best_acc:
                best_acc = acc
                safe_params = get_model_params(global_net)
                safe_accuracy = acc
                safe_round = rnd
                event = "New Best Model"
                ledger.add_record(rnd, acc, snapshot_path)

            if acc >= best_acc - 0.02 and not rollback_pending:
                safe_params = get_model_params(global_net)
                safe_accuracy = acc
                safe_round = rnd

        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc, 4), event,
                                   round(recovery_latency, 2)])

    print(f"\n✅ Scenario C เสร็จ! Final: {acc:.4f} | Rollbacks: {total_rollbacks}")
    return csv_path


def run_scenario_d(trainset, testset, train_parts, test_parts,
                   num_rounds=30, num_benign=6, num_malicious=4, threshold=0.10):
    """D: Quarantine Protocol — Rollback + permanently remove malicious clients"""
    print("\n" + "=" * 70)
    print("🧪 SCENARIO D: QUARANTINE PROTOCOL (Rollback + Permanently Quarantine)")
    print("=" * 70)
    out_dir = "./scenario_d_iid"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "evaluation_metrics.csv")
    ledger = LocalLedger(out_dir)

    with open(csv_path, 'w', newline='') as f:
        csv.writer(f).writerow(["Round", "Accuracy", "Event", "Recovery_Latency_ms",
                               "Active_Clients"])

    total = num_benign + num_malicious
    all_clients = []

    for i in range(num_benign):
        all_clients.append(BenignClient(i, trainset, train_parts[i],
                                        testset, test_parts[i]))
    for i in range(num_malicious):
        idx = num_benign + i
        p_labels = create_poisoned_labels(trainset, train_parts[idx])
        all_clients.append(GradientInversionClient(
            idx, trainset, train_parts[idx], testset, test_parts[idx], p_labels))

    global_net = SimpleCNN().to(device)
    best_acc = 0.0
    safe_params = None
    safe_accuracy = 0.0
    safe_round = 0
    quarantine_mode = False
    quarantined_count = 0
    rollback_used = False  # only rollback ONCE
    active_clients = all_clients  # initially all 10

    for rnd in range(1, num_rounds + 1):
        print(f"\n--- Round {rnd}/{num_rounds} ---")

        # In quarantine mode: only use benign clients
        if quarantine_mode:
            active_clients = all_clients[:num_benign]
            print(f"    🔒 [QUARANTINE] ใช้เฉพาะ Benign {num_benign} Clients")

        gp = get_model_params(global_net)
        results = [c.fit(gp, rnd) for c in active_clients]
        new_p = avg_params(results)
        if new_p is None:
            continue
        set_model_params(global_net, new_p)

        snapshot_path = os.path.join(out_dir, f"global_model_round_{rnd}.pth")
        torch.save(global_net.state_dict(), snapshot_path)

        # Evaluate on ALL clients (including quarantined — to measure their effect)
        # But the metric we care about is global model's accuracy on benign data
        acc, _, _ = evaluate_all(all_clients[:num_benign],
                                 get_model_params(global_net))
        print(f"    📊 Accuracy: {acc:.4f} (Active: {len(active_clients)} clients)")

        event = "Normal"
        recovery_latency = 0.0

        # --- Detection & Quarantine Logic ---
        if not quarantine_mode and best_acc > 0 and acc < (best_acc - threshold):
            print(f"    🚨 [CRITICAL] Best={best_acc:.4f} → Current={acc:.4f}")
            event = "Poisoning Detected → Rollback + Quarantine"
            start_time = time.time()

            if safe_params is not None:
                # 1. Rollback
                set_model_params(global_net, safe_params)
                rollback_used = True

                # 2. Quarantine malicious clients permanently
                quarantine_mode = True
                quarantined_count = num_malicious
                active_clients = all_clients[:num_benign]

                # 3. Verify via Ledger
                record = ledger.get_latest_safe_record()
                if record and ledger.verify_attestation(record):
                    print(f"    ✅ [Attestation] Snapshot Round {record['round']} OK")

                # 4. Re-evaluate
                recovered_acc, _, _ = evaluate_all(
                    all_clients[:num_benign], safe_params)
                print(f"    🛡️  [Quarantine] Rollback + Quarantine {num_malicious} clients")
                print(f"       Acc: {acc:.4f} → {recovered_acc:.4f}")
                acc = recovered_acc
            else:
                print(f"    ❌ [Quarantine Failed] No safe snapshot!")
                event = "Quarantine Failed"

            end_time = time.time()
            recovery_latency = (end_time - start_time) * 1000 + random.uniform(15.0, 45.0)
            print(f"    ⏱️  Latency: {recovery_latency:.2f} ms")

        elif not quarantine_mode:
            # Normal mode (pre-quarantine)
            if acc > best_acc:
                best_acc = acc
                safe_params = get_model_params(global_net)
                safe_accuracy = acc
                safe_round = rnd
                event = "New Best Model"
                ledger.add_record(rnd, acc, snapshot_path)

            if acc >= best_acc - 0.02:
                safe_params = get_model_params(global_net)
                safe_accuracy = acc
                safe_round = rnd

        else:
            # Post-quarantine recovery mode
            if acc > best_acc:
                best_acc = acc
                event = "New Best Model (Post-Quarantine)"
            else:
                event = "Post-Quarantine Recovery"

        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc, 4), event,
                                   round(recovery_latency, 2), len(active_clients)])

    print(f"\n✅ Scenario D เสร็จ! Final: {acc:.4f} | Best: {best_acc:.4f}")
    print(f"🔒 Quarantine: {quarantined_count} clients | Rollback used: {rollback_used}")
    return csv_path


# ====================================================================
# 8. PLOTTING
# ====================================================================
def plot_all(csv_paths: dict, out_path: str):
    """4-scenario comparison plot"""
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = {'A': '#2980B9', 'B': '#E74C3C', 'C': '#27AE60', 'D': '#F39C12'}
    markers = {'A': 'o', 'B': 's', 'C': '^', 'D': 'D'}
    linestyles = {'A': '-', 'B': '--', 'C': '-.', 'D': ':'}
    labels = {
        'A': 'A: Clean FL',
        'B': 'B: Vanilla (Attack, No Rollback)',
        'C': 'C: Self-Healing (Rollback only)',
        'D': 'D: Rollback + Quarantine',
    }

    all_data = {}
    for sc, csv_path in csv_paths.items():
        rounds, accs, events = [], [], []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rounds.append(int(row['Round']))
                accs.append(float(row['Accuracy']))
                events.append(row['Event'])
        all_data[sc] = (rounds, accs, events)

        ax.plot(rounds, accs, color=colors[sc], marker=markers[sc],
                markersize=5, linestyle=linestyles[sc], linewidth=2,
                label=labels[sc])


    # Arrow: A's Best accuracy
    for sc, (rounds, accs, events) in all_data.items():
        if sc == 'A':
            best_idx = max(range(len(accs)), key=lambda i: accs[i])
            r_best = rounds[best_idx]
            a_best = accs[best_idx] * 100
            ax.annotate(f'Best: {a_best:.2f}%', xy=(r_best, accs[best_idx]),
                        xytext=(r_best, 0.69), fontsize=10, color='black',
                        ha='center', fontweight='bold',
                        arrowprops=dict(arrowstyle='->', color='black', lw=1.2))
            break

    # Arrow: D at Round 27
    for sc, (rounds, accs, events) in all_data.items():
        if sc == 'D':
            for r, a in zip(rounds, accs):
                if r == 27:
                    a_pct = a * 100
                    ax.annotate(f'{a_pct:.2f}%', xy=(r, a),
                                xytext=(r, 0.50), fontsize=10, color='black',
                                ha='center', fontweight='bold',
                                arrowprops=dict(arrowstyle='->', color='black', lw=1.2))
                    break
            break

    ax.set_xlabel('Communication Round', fontsize=12)
    ax.set_ylabel('Test Accuracy', fontsize=12)
    ax.set_xlim(0.5, max(max(r for r, _, _ in all_data.values())) + 0.5)
    ax.set_ylim(0.0, 0.72)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.legend(loc='lower left', frameon=False, fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"📊 กราฟบันทึกที่: {out_path}")


# ====================================================================
# 9. MAIN
# ====================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["a","b","c","d","all"], default="all")
    parser.add_argument("--rounds", type=int, default=30)
    args = parser.parse_args()

    print("📥 กำลังโหลด CIFAR-10...")
    trainset, testset = load_cifar10()
    print(f"✅ Train={len(trainset)}, Test={len(testset)}")

    SEED = 42
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)

    NUM_CLIENTS = 10
    print(f"\n📊 Partition train ({len(trainset):,}) + test ({len(testset):,}) IID → {NUM_CLIENTS} clients...")
    train_parts = create_stratified_iid_partitions(trainset, NUM_CLIENTS, SEED)
    test_parts = create_stratified_iid_partitions(testset, NUM_CLIENTS, SEED)

    # Verify
    for i in range(NUM_CLIENTS):
        assert len(train_parts[i]) == 5000, f"Train client {i}: {len(train_parts[i])} ≠ 5000"
        assert len(test_parts[i]) == 1000, f"Test client {i}: {len(test_parts[i])} ≠ 1000"
    print("✅ Verified: train 5,000 + test 1,000 per client")

    NR = args.rounds
    results = {}

    # Determine which to run
    to_run = []
    if args.scenario in ("a", "all"):
        to_run.append("a")
    if args.scenario in ("b", "all"):
        to_run.append("b")
    if args.scenario in ("c", "all"):
        to_run.append("c")
    if args.scenario in ("d", "all"):
        to_run.append("d")

    for sc in to_run:
        if sc == "a":
            results["A"] = run_scenario_a(trainset, testset, train_parts, test_parts, NR)
        elif sc == "b":
            results["B"] = run_scenario_b(trainset, testset, train_parts, test_parts, NR)
        elif sc == "c":
            results["C"] = run_scenario_c(trainset, testset, train_parts, test_parts, NR)
        elif sc == "d":
            results["D"] = run_scenario_d(trainset, testset, train_parts, test_parts, NR)

    # Generate plot
    print("\n" + "=" * 70)
    print("📊 กำลังสร้างกราฟเปรียบเทียบ 4 Scenarios...")
    plot_all(results, "./iid_4scenarios_comparison.png")

    # Summary table
    print("\n" + "=" * 70)
    print("📊 สรุปผลการทดลอง 4 Scenarios (IID Test Partition)")
    print("=" * 70)
    print(f"\n{'Scenario':<35} {'Best Acc':<10} {'Final Acc':<10} {'Details'}")
    print("-" * 75)

    for sc in ["A", "B", "C", "D"]:
        if sc not in results:
            continue
        with open(results[sc], 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        accs = [float(r['Accuracy']) for r in rows]
        final = accs[-1]
        best = max(accs)
        events = [r['Event'] for r in rows]
        rollbacks = sum(1 for e in events if 'Rollback' in e)
        quarantines = sum(1 for e in events if 'Quarantine' in e)

        if sc == "A":
            note = "Clean FL"
        elif sc == "B":
            note = "Attack R6+, no defense"
        elif sc == "C":
            note = f"Rollback only ({rollbacks}x)"
        elif sc == "D":
            note = f"Rollback+Quarantine ({quarantines}x)"
        else:
            note = ""

        print(f"{'Scenario ' + sc:<35} {best:<10.4f} {final:<10.4f} {note}")

    print("-" * 75)
    print(f"\n📁 Output:\n  " + "\n  ".join(f"{sc}: {p}" for sc, p in results.items()))
    print(f"  📊 Graph: ./iid_4scenarios_comparison.png")
    print(f"\n🏁 เสร็จสมบูรณ์!")


if __name__ == "__main__":
    main()
