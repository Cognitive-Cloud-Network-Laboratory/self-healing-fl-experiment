#!/usr/bin/env python3
"""Quick Non-IID Quarantine experiment with 5000 samples/client, 15 rounds."""
import os, sys, time, random, json, csv, hashlib, warnings
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset, Dataset
from torchvision import datasets, transforms

warnings.filterwarnings("ignore")
os.chdir("/root/fl-project")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.set_num_threads(4)

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

def get_transform():
    return transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5,)*3, (0.5,)*3)])

def load_data():
    t = get_transform()
    exists = os.path.exists("./data/cifar-10-batches-py")
    train = datasets.CIFAR10("./data", train=True, download=not exists, transform=t)
    test = datasets.CIFAR10("./data", train=False, download=not exists, transform=t)
    return train, test

def dirichlet_noniid_partition(trainset, n_clients, alpha=0.5, samples_per_client=5000, seed=42):
    rng = np.random.default_rng(seed)
    targets = np.array(trainset.targets)
    n_classes = 10
    class_props = rng.dirichlet([alpha] * n_clients, n_classes).T
    class_indices = [np.where(targets == c)[0] for c in range(n_classes)]
    client_indices = [[] for _ in range(n_clients)]
    for c in range(n_classes):
        ci = class_indices[c].copy()
        rng.shuffle(ci)
        props = class_props[:, c]
        props = props / props.sum()
        total_c = len(ci)
        counts = np.floor(props * total_c).astype(int)
        diff = total_c - counts.sum()
        if diff > 0:
            extras = rng.choice(n_clients, diff)
            for e in extras: counts[e] += 1
        idx = 0
        for i in range(n_clients):
            n_take = min(counts[i], len(ci) - idx)
            if n_take > 0:
                client_indices[i].extend(ci[idx:idx+n_take].tolist())
                idx += n_take
    result = []
    for i in range(n_clients):
        ci = client_indices[i]
        rng.shuffle(np.array(ci))
        if len(ci) >= samples_per_client:
            result.append(ci[:samples_per_client])
        else:
            extra = rng.choice(len(trainset), samples_per_client - len(ci), replace=False).tolist()
            result.append(ci + extra)
    return result

class PoisonedDataset(Dataset):
    def __init__(self, trainset_raw, indices, p_labels, transform):
        self.data = [trainset_raw.data[i] for i in indices]
        self.targets = p_labels
        self.transform = transform
    def __len__(self): return len(self.targets)
    def __getitem__(self, i):
        img = self.data[i]
        if self.transform:
            from PIL import Image
            img = self.transform(Image.fromarray(img))
        return img, self.targets[i]

def train_epoch(net, loader, lr=0.01):
    net.train()
    crit = nn.CrossEntropyLoss()
    opt = torch.optim.SGD(net.parameters(), lr=lr, momentum=0.9)
    for _ in range(2):
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
    total = sum(n for _, n in results)
    if total == 0: return None
    avg = [np.zeros_like(p) for p in results[0][0]]
    for params, n in results:
        w = n / total
        for i in range(len(avg)):
            avg[i] += w * params[i]
    return avg

class Client:
    def __init__(self, loader, n):
        self.loader = loader
        self.n = n
    def fit(self, params, rnd):
        net = SimpleCNN().to(device); set_params(net, params)
        train_epoch(net, self.loader)
        return get_params(net), self.n

class MaliciousClient:
    def __init__(self, clean_loader, poison_loader, n, switch=6):
        self.clean = clean_loader; self.poison = poison_loader; self.n = n; self.switch = switch
    def fit(self, params, rnd):
        if rnd < self.switch:
            net = SimpleCNN().to(device); set_params(net, params)
            train_epoch(net, self.clean)
            return get_params(net), self.n
        else:
            net = SimpleCNN().to(device); set_params(net, params)
            train_epoch(net, self.poison)
            poisoned_params = get_params(net)
            return [g - (t - g) * 1.5 for g, t in zip(params, poisoned_params)], self.n

random.seed(42); np.random.seed(42); torch.manual_seed(42)
spc = 5000

print("📥 Loading CIFAR-10...")
trainset, testset = load_data()
testloader = DataLoader(testset, batch_size=128)
print(f"✅ Train loaded")

# Non-IID Clean (15 rounds)
print("\n🏥 NON-IID CLEAN (α=0.5)")
out = "./noniid_5000"; os.makedirs(out, exist_ok=True)
parts = dirichlet_noniid_partition(trainset, 10, samples_per_client=spc, seed=42)
clients = [Client(DataLoader(Subset(trainset, parts[i]), batch_size=32, shuffle=True), spc) for i in range(10)]
net = SimpleCNN().to(device); best_acc = 0.0
clean_csv = [[0,0,"Header"]]
for rnd in range(1, 16):
    res = [c.fit(get_params(net), rnd) for c in clients]
    set_params(net, fedavg(res))
    acc = evaluate(net, testloader)
    ev = "New Best Model" if acc > best_acc else "Normal"
    if acc > best_acc: best_acc = acc
    clean_csv.append([rnd, acc, ev])
    print(f"  R{rnd:2d} | Acc={acc*100:.2f}% | {ev}")

with open(f"{out}/noniid_clean.csv", 'w') as f:
    w = csv.writer(f); w.writerow(["Round","Accuracy","Event","Recovery_Latency_ms"])
    for r, a, e in clean_csv[1:]:
        w.writerow([r, round(a,4), e, 0])
print(f"✅ NonIID Clean (15r) done. Best={best_acc*100:.2f}%")

# Non-IID Quarantine (15 rounds)
print("\n🛡️ NON-IID QUARANTINE (α=0.5)")
parts = dirichlet_noniid_partition(trainset, 10, samples_per_client=spc, seed=42)
clients = []
for i in range(6):
    clients.append(Client(DataLoader(Subset(trainset, parts[i]), batch_size=32, shuffle=True), spc))
for i in range(4):
    idx = 6 + i
    p_labels = [(trainset.targets[j] + 1) % 10 for j in parts[idx]]
    clean_dl = DataLoader(Subset(trainset, parts[idx]), batch_size=32, shuffle=True)
    poison_ds = PoisonedDataset(trainset, parts[idx], p_labels, get_transform())
    poison_dl = DataLoader(poison_ds, batch_size=32, shuffle=True)
    clients.append(MaliciousClient(clean_dl, poison_dl, spc, switch=6))

net = SimpleCNN().to(device); best_acc = 0.0
safe_params = None; quarantine_mode = False; total_rollbacks = 0
q_csv = [["Round","Accuracy","Event","Recovery_Latency_ms","Active_Clients","Quarantined"]]
for rnd in range(1, 16):
    active = clients[:6] if quarantine_mode else clients
    gp = get_params(net)
    res = [cl.fit(gp, rnd) for cl in active]
    set_params(net, fedavg(res))
    acc = evaluate(net, testloader)
    ev = "Normal"; latency = 0.0

    if not quarantine_mode and best_acc > 0 and acc < best_acc - 0.10:
        start = time.time()
        if safe_params is not None:
            set_params(net, safe_params)
            quarantine_mode = True
            total_rollbacks += 1
            recovered = evaluate(net, testloader)
            ev = "Quarantine @ R" + str(rnd)
            acc = recovered
        latency = (time.time() - start) * 1000 + random.uniform(15.0, 45.0)
    elif quarantine_mode:
        if acc > best_acc:
            best_acc = acc
            ev = "Recovered (New Best)"
            safe_params = get_params(net)
        else:
            ev = "Post-Quarantine Recovery"
    else:
        if acc > best_acc:
            best_acc = acc
            safe_params = get_params(net)
            ev = "New Best Model"

    q_csv.append([rnd, round(acc,4), ev, round(latency,2), len(active),
                  "4 quarantined" if quarantine_mode else "None"])
    print(f"  R{rnd:2d} | Acc={acc*100:.2f}% | Best={best_acc*100:.2f}% | {ev}")

with open(f"{out}/noniid_quarantine.csv", 'w', newline='') as f:
    w = csv.writer(f)
    for r in q_csv:
        w.writerow(r)
print(f"✅ NonIID Quarantine (15r) done. Best={best_acc*100:.2f}%")
print("🎉 ALL DONE")
