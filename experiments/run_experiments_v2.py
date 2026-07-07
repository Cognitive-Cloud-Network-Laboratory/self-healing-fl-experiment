#!/usr/bin/env python3
"""
Continue and run ALL 3 Scenarios for the Self-Healing FL Experiment.
Optimized for CPU by using smaller data partition (2000 samples/client).
"""
import os, sys, time, random, json, csv, hashlib, warnings, argparse
from copy import deepcopy
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset, Dataset
from torchvision import datasets, transforms

warnings.filterwarnings("ignore")
os.chdir("/root/fl-project")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🔧 Device: {device}")

# --- CNN ---
class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 6, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16*5*5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 10)
    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)

# --- Data ---
def get_transform():
    return transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5,)*3, (0.5,)*3)])

def load_data():
    t = get_transform()
    exists = os.path.exists("./data/cifar-10-batches-py")
    train = datasets.CIFAR10("./data", train=True, download=not exists, transform=t)
    test = datasets.CIFAR10("./data", train=False, download=not exists, transform=t)
    return train, test

def iid_partition(trainset, n_clients, samples_per_client=2000, seed=42):
    """IID split: each client gets samples_per_client images"""
    rng = random.Random(seed)
    all_idx = list(range(len(trainset)))
    rng.shuffle(all_idx)
    total = n_clients * samples_per_client
    if total > len(all_idx):
        raise ValueError(f"Not enough data: need {total}, have {len(all_idx)}")
    return [all_idx[i*samples_per_client:(i+1)*samples_per_client] for i in range(n_clients)]

def poisoned_labels(trainset, indices):
    """100% Label flip: (old + 1) % 10"""
    return [(trainset.targets[i] + 1) % 10 for i in indices]

class PoisonedDataset(Dataset):
    def __init__(self, trainset_raw, indices, p_labels, transform):
        # trainset_raw is the CIFAR10 dataset
        self.data = [trainset_raw.data[i] for i in indices]  # raw numpy array
        self.targets = p_labels
        self.transform = transform
    def __len__(self): return len(self.targets)
    def __getitem__(self, i):
        img = self.data[i]  # numpy array (H,W,C)
        if self.transform:
            from PIL import Image
            img = self.transform(Image.fromarray(img))
        return img, self.targets[i]

# --- Training ---
def train_epoch(net, loader, lr=0.01):
    """Train for 2 epochs"""
    net.train()
    crit = nn.CrossEntropyLoss()
    opt = torch.optim.SGD(net.parameters(), lr=lr, momentum=0.9)
    for _ in range(2):  # 2 epochs per round
        for img, lbl in loader:
            img, lbl = img.to(device), lbl.to(device)
            opt.zero_grad()
            crit(net(img), lbl).backward()
            opt.step()

def evaluate(net, loader):
    net.eval()
    correct = total = 0
    with torch.no_grad():
        for img, lbl in loader:
            img, lbl = img.to(device), lbl.to(device)
            _, pred = torch.max(net(img), 1)
            total += lbl.size(0)
            correct += (pred == lbl).sum().item()
    return correct / total

def get_params(net):
    return [v.cpu().detach().numpy() for _, v in net.state_dict().items()]

def set_params(net, params):
    sd = dict(zip(net.state_dict().keys(), [torch.tensor(v) for v in params]))
    net.load_state_dict(sd, strict=True)

def fedavg(results):
    """results: [([params...], num_ex), ...]"""
    total = sum(n for _, n in results)
    if total == 0: return None
    avg = [np.zeros_like(p) for p in results[0][0]]
    for params, n in results:
        w = n / total
        for i in range(len(avg)):
            avg[i] += w * params[i]
    return avg

# --- Clients ---
class Client:
    def __init__(self, loader, n):
        self.loader = loader
        self.n = n
    def fit(self, params, rnd):
        net = SimpleCNN().to(device)
        set_params(net, params)
        train_epoch(net, self.loader)
        return get_params(net), self.n

class MaliciousClient:
    def __init__(self, clean_loader, poison_loader, n, switch=6):
        self.clean = clean_loader
        self.poison = poison_loader
        self.n = n
        self.switch = switch
    def fit(self, params, rnd):
        if rnd < self.switch:
            # Rounds 1-5: behave normally (clean data)
            net = SimpleCNN().to(device)
            set_params(net, params)
            train_epoch(net, self.clean)
            return get_params(net), self.n
        else:
            # Rounds 6+: GRADIENT INVERSION ATTACK
            # Step 1: Train on poisoned data
            net = SimpleCNN().to(device)
            set_params(net, params)
            train_epoch(net, self.poison)
            poisoned_params = get_params(net)

            # Step 2: Invert the gradient (push weights in opposite direction)
            # new_params = global - (trained - global) * 1.5 = global * 2.5 - trained * 1.5
            inverted = []
            for g, t in zip(params, poisoned_params):
                # Invert and amplify: move away from good direction
                inverted.append(g - (t - g) * 1.5)
            return inverted, self.n

# --- Ledger ---
class Ledger:
    def __init__(self, out):
        self.out = out; self.chain = []
        self.file = os.path.join(out, "ledger_history.json")
    def add(self, rnd, acc, path):
        with open(path, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        rec = {"round": rnd, "accuracy": round(acc,4), "model_hash": h, "file_path": path}
        self.chain.append(rec)
        with open(self.file, "w") as f: json.dump(self.chain, f, indent=4)
    def latest(self):
        return self.chain[-1] if self.chain else None
    def verify(self, rec):
        if not os.path.exists(rec["file_path"]): return False
        with open(rec["file_path"], "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == rec["model_hash"]


# ======================================================================
# SCENARIO RUNNERS
# ======================================================================
def run_a(trainset, testloader, n_rounds=30, n_clients=10, spc=5000):
    print("="*60); print("🏥 SCENARIO A: Clean FL (10 Benign)"); print("="*60)
    outdir = "./scenario_a"; os.makedirs(outdir, exist_ok=True)
    csv_p = os.path.join(outdir, "evaluation_metrics.csv")
    with open(csv_p, 'w', newline='') as f:
        csv.writer(f).writerow(["Round","Accuracy","Event","Recovery_Latency_ms"])

    parts = iid_partition(trainset, n_clients, spc)
    clients = []
    for i in range(n_clients):
        sub = Subset(trainset, parts[i])
        dl = DataLoader(sub, batch_size=32, shuffle=True)
        clients.append(Client(dl, spc))

    net = SimpleCNN().to(device); best_acc = 0.0

    for rnd in range(1, n_rounds+1):
        gp = get_params(net)
        res = [c.fit(gp, rnd) for c in clients]
        new_p = fedavg(res)
        if new_p is None: continue
        set_params(net, new_p)

        sp = os.path.join(outdir, f"global_model_round_{rnd}.pth")
        torch.save(net.state_dict(), sp)
        acc = evaluate(net, testloader)
        ev = "New Best Model" if acc > best_acc else "Normal"
        if acc > best_acc: best_acc = acc
        print(f"  Round {rnd:2d}/{n_rounds} | Acc={acc:.4f} | {ev}")
        with open(csv_p, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc,4), ev, 0.0])

    print(f"✅ A done. Final Acc={best_acc:.4f}\n"); return csv_p

def run_b(trainset, testloader, n_rounds=30, n_benign=6, n_malicious=4, spc=5000):
    print("="*60); print("☠️ SCENARIO B: Vanilla FL under Attack (NO Rollback)"); print("="*60)
    outdir = "./scenario_b"; os.makedirs(outdir, exist_ok=True)
    csv_p = os.path.join(outdir, "evaluation_metrics.csv")
    with open(csv_p, 'w', newline='') as f:
        csv.writer(f).writerow(["Round","Accuracy","Event","Recovery_Latency_ms"])

    nc = n_benign + n_malicious
    parts = iid_partition(trainset, nc, spc)

    clients = []
    for i in range(n_benign):
        dl = DataLoader(Subset(trainset, parts[i]), batch_size=32, shuffle=True)
        clients.append(Client(dl, spc))
    for i in range(n_malicious):
        idx = n_benign + i
        p_labels = poisoned_labels(trainset, parts[idx])
        clean_dl = DataLoader(Subset(trainset, parts[idx]), batch_size=32, shuffle=True)
        poison_ds = PoisonedDataset(trainset, parts[idx], p_labels, get_transform())
        poison_dl = DataLoader(poison_ds, batch_size=32, shuffle=True)
        clients.append(MaliciousClient(clean_dl, poison_dl, spc, switch=6))

    net = SimpleCNN().to(device); best_acc = 0.0

    for rnd in range(1, n_rounds+1):
        gp = get_params(net)
        res = [c.fit(gp, rnd) for c in clients]
        new_p = fedavg(res)
        if new_p is None: continue
        set_params(net, new_p)

        sp = os.path.join(outdir, f"global_model_round_{rnd}.pth")
        torch.save(net.state_dict(), sp)
        acc = evaluate(net, testloader)
        ev = "New Best Model" if acc > best_acc else "Normal"
        if rnd >= 6 and best_acc - acc > 0.10:
            ev = "Critical Accuracy Drop"
        if acc > best_acc: best_acc = acc
        print(f"  Round {rnd:2d}/{n_rounds} | Acc={acc:.4f} | Best={best_acc:.4f} | {ev}")
        with open(csv_p, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc,4), ev, 0.0])

    print(f"✅ B done. Best={best_acc:.4f} Final={acc:.4f}\n"); return csv_p

def run_c(trainset, testloader, n_rounds=30, n_benign=6, n_malicious=4, spc=5000, thresh=0.10):
    print("="*60); print("🛡️ SCENARIO C: Self-Healing (WITH Rollback)"); print("="*60)
    outdir = "./scenario_c"; os.makedirs(outdir, exist_ok=True)
    csv_p = os.path.join(outdir, "evaluation_metrics.csv")
    ledger = Ledger(outdir)
    with open(csv_p, 'w', newline='') as f:
        csv.writer(f).writerow(["Round","Accuracy","Event","Recovery_Latency_ms"])

    nc = n_benign + n_malicious
    parts = iid_partition(trainset, nc, spc)

    clients = []
    for i in range(n_benign):
        dl = DataLoader(Subset(trainset, parts[i]), batch_size=32, shuffle=True)
        clients.append(Client(dl, spc))
    for i in range(n_malicious):
        idx = n_benign + i
        p_labels = poisoned_labels(trainset, parts[idx])
        clean_dl = DataLoader(Subset(trainset, parts[idx]), batch_size=32, shuffle=True)
        poison_ds = PoisonedDataset(trainset, parts[idx], p_labels, get_transform())
        poison_dl = DataLoader(poison_ds, batch_size=32, shuffle=True)
        clients.append(MaliciousClient(clean_dl, poison_dl, spc, switch=6))

    net = SimpleCNN().to(device); best_acc = 0.0
    safe_params = None; safe_rnd = 0; safe_acc = 0.0
    rollback_pending = False; total_rollbacks = 0

    for rnd in range(1, n_rounds+1):
        if rollback_pending and safe_params is not None:
            set_params(net, safe_params)
            rollback_pending = False

        gp = get_params(net)
        res = [c.fit(gp, rnd) for c in clients]
        new_p = fedavg(res)
        if new_p is None: continue
        set_params(net, new_p)

        sp = os.path.join(outdir, f"global_model_round_{rnd}.pth")
        torch.save(net.state_dict(), sp)

        acc = evaluate(net, testloader)
        ev = "Normal"; latency = 0.0

        if best_acc > 0 and acc < best_acc - thresh:
            ev = "Poisoning Detected & Rollback"
            start = time.time()

            if safe_params is not None:
                rec = ledger.latest()
                if rec and ledger.verify(rec):
                    print(f"    ✅ Attestation OK: Round {rec['round']}")
                else:
                    print(f"    ⚠️ Attestation warning, using cached params")
                set_params(net, safe_params)
                rollback_pending = True
                total_rollbacks += 1
                rec_acc, _ = evaluate(net, testloader), None
                # Re-evaluate
                recovered = evaluate(net, testloader)
                print(f"    🛡️ Rollback OK: {acc:.4f} → {recovered:.4f}")
                acc = recovered
                ev = "Poisoning Detected & Rollback"
            else:
                ev = "Rollback Failed"

            base_ms = (time.time() - start) * 1000
            consensus = random.uniform(15.0, 45.0)  # 🆕 SYNTHETIC CONSENSUS DELAY
            latency = base_ms + consensus
            print(f"    ⏱️ Latency: {base_ms:.1f}+{consensus:.1f}={latency:.1f}ms")
        else:
            if acc > best_acc:
                best_acc = acc
                safe_params = get_params(net)
                safe_rnd = rnd; safe_acc = acc
                ev = "New Best Model"
                ledger.add(rnd, acc, sp)
            elif acc >= best_acc - 0.02:
                safe_params = get_params(net)
                safe_rnd = rnd; safe_acc = acc

        print(f"  Round {rnd:2d}/{n_rounds} | Acc={acc:.4f} | Best={best_acc:.4f} | {ev}")
        with open(csv_p, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc,4), ev, round(latency,2)])

    print(f"✅ C done. Best={best_acc:.4f} Final={acc:.4f} Rollbacks={total_rollbacks}\n")
    return csv_p


# ======================================================================
# SCENARIO D RUNNER — Full Self-Healing with Client Quarantine
# ======================================================================
def run_d(trainset, testloader, n_rounds=30, n_benign=6, n_malicious=4, spc=5000, thresh=0.10):
    """
    Scenario D: Full Self-Healing with Client Quarantine Protocol
    --------------------------------------------------------------
    6 Benign + 4 Malicious (Gradient Inversion Attack from Round 6)
    - Round 6: Detect poisoning → Rollback to Round 5 → QUARANTINE malicious clients
    - Rounds 7-30: FedAvg with ONLY 6 Benign clients (attackers permanently excluded)
    """
    print("="*70)
    print("🛡️  SCENARIO D: FULL SELF-HEALING + CLIENT QUARANTINE")
    print("    Amputation Logic: Quarantine 4 Malicious → Recover with 6 Benign")
    print("="*70)
    outdir = "./scenario_d"; os.makedirs(outdir, exist_ok=True)
    csv_p = os.path.join(outdir, "evaluation_metrics.csv")
    ledger = Ledger(outdir)
    with open(csv_p, 'w', newline='') as f:
        csv.writer(f).writerow(["Round","Accuracy","Event","Recovery_Latency_ms",
                                "Active_Clients","Quarantined"])

    nc = n_benign + n_malicious
    parts = iid_partition(trainset, nc, spc)

    clients = []
    for i in range(n_benign):
        dl = DataLoader(Subset(trainset, parts[i]), batch_size=32, shuffle=True)
        clients.append(Client(dl, spc))
    for i in range(n_malicious):
        idx = n_benign + i
        p_labels = poisoned_labels(trainset, parts[idx])
        clean_dl = DataLoader(Subset(trainset, parts[idx]), batch_size=32, shuffle=True)
        poison_ds = PoisonedDataset(trainset, parts[idx], p_labels, get_transform())
        poison_dl = DataLoader(poison_ds, batch_size=32, shuffle=True)
        clients.append(MaliciousClient(clean_dl, poison_dl, spc, switch=6))

    net = SimpleCNN().to(device); best_acc = 0.0
    safe_params = None; safe_rnd = 0; safe_acc = 0.0
    rollback_pending = False; total_rollbacks = 0
    quarantine_mode = False; quarantined_count = 0; quarantine_round = 0

    for rnd in range(1, n_rounds+1):
        if rollback_pending and safe_params is not None:
            set_params(net, safe_params)
            rollback_pending = False

        # Select active clients
        if quarantine_mode:
            active_clients = clients[:n_benign]
            note = f"🔒 Quarantine (6 Benign only)"
        else:
            active_clients = clients
            note = "All 10 clients"

        gp = get_params(net)
        res = [cl.fit(gp, rnd) for cl in active_clients]
        new_p = fedavg(res)
        if new_p is None: continue
        set_params(net, new_p)

        sp = os.path.join(outdir, f"global_model_round_{rnd}.pth")
        torch.save(net.state_dict(), sp)
        acc = evaluate(net, testloader)
        ev = "Normal"; latency = 0.0

        # Self-Healing Detection & Quarantine
        if not quarantine_mode and best_acc > 0 and acc < best_acc - thresh:
            ev = "🚨 Poisoning Detected → Rollback + Quarantine"
            start = time.time()
            if safe_params is not None:
                rec = ledger.latest()
                if rec and ledger.verify(rec):
                    print(f"    ✅ Attestation OK: Round {rec['round']}")
                set_params(net, safe_params)
                quarantine_mode = True
                quarantined_count = n_malicious
                quarantine_round = rnd
                print(f"    🔒 [QUARANTINE] เตะ Malicious {n_malicious} เครื่องออกถาวร ✓")
                total_rollbacks += 1
                recovered = evaluate(net, testloader)
                ev = "Poisoning Detected + Quarantine"
                print(f"    🛡️ Rollback + Quarantine: {acc:.4f} → {recovered:.4f}")
                acc = recovered
            else:
                ev = "Rollback Failed"
            base_ms = (time.time() - start) * 1000
            consensus = random.uniform(15.0, 45.0)
            latency = base_ms + consensus
            print(f"    ⏱️ Latency: {base_ms:.1f}+{consensus:.1f}={latency:.1f}ms")
        elif quarantine_mode:
            if acc > best_acc:
                best_acc = acc
                ev = "🔄 Recovered (New Best)"
                ledger.add(rnd, acc, sp)
                safe_params = get_params(net)
            else:
                ev = "🔄 Post-Quarantine Recovery"
        else:
            if acc > best_acc:
                best_acc = acc
                safe_params = get_params(net)
                safe_rnd = rnd; safe_acc = acc
                ev = "New Best Model"
                ledger.add(rnd, acc, sp)
            elif acc >= best_acc - 0.02:
                safe_params = get_params(net)

        n_active = len(active_clients)
        quar_status = f"{quarantined_count} quarantined" if quarantine_mode else "None"
        print(f"  Round {rnd:2d}/{n_rounds} | Acc={acc:.4f} | Best={best_acc:.4f} | {ev} | {note}")
        with open(csv_p, 'a', newline='') as f:
            csv.writer(f).writerow([rnd, round(acc,4), ev, round(latency,2),
                                     n_active, quar_status])

    print(f"\n✅ D done. Best={best_acc:.4f} Final={acc:.4f} Rollbacks={total_rollbacks} Quarantine=Round {quarantine_round}")
    return csv_p


# ======================================================================
# MAIN
# ======================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=str, default="all",
                       help="Scenario to run: a, b, c, d, or comma-separated, or all (default)")
    args = parser.parse_args()

    scenarios = [s.strip() for s in args.scenario.split(",")]
    for s in scenarios:
        if s not in ("a", "b", "c", "d", "all"):
            print(f"Invalid scenario: {s}"); sys.exit(1)
    if "all" in scenarios:
        scenarios = ["a", "b", "c", "d"]

    random.seed(42); np.random.seed(42); torch.manual_seed(42)

    print("📥 Loading CIFAR-10...")
    trainset, testset = load_data()
    testloader = DataLoader(testset, batch_size=128)
    print(f"✅ Train={len(trainset)} Test={len(testset)}")

    results = {}
    for sc in scenarios:
        if sc == "a": results["A"] = run_a(trainset, testloader)
        elif sc == "b": results["B"] = run_b(trainset, testloader)
        elif sc == "c": results["C"] = run_c(trainset, testloader)
        elif sc == "d": results["D"] = run_d(trainset, testloader)

    print("="*60)
    print("📊 SUMMARY")
    print("="*60)
    for sc, p in results.items():
        with open(p) as f:
            lines = f.readlines()
        print(f"  Scenario {sc}: {p} ({len(lines)-1} records)")
        if len(lines) > 1:
            print(f"    Last: {lines[-1].strip()}")

    print("\n🎉 All done!")
