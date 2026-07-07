import flwr as fl
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

# ==========================================
# 1. นิยามโมเดล CNN ขนาดเล็ก (สำหรับ CIFAR-10)
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
# 2. ฟังก์ชันโหลดข้อมูลแบบวางยา (Data Poisoning)
# ==========================================
def load_poisoned_data():
    """โหลดชุดข้อมูล CIFAR-10 และทำการสลับ Label (วางยา)"""
    import os
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])
    
    # ตรวจสอบว่ามีข้อมูลแล้วหรือยัง
    data_exists = os.path.exists("./data/cifar-10-batches-py")
    
    # โหลดข้อมูล Train (ข้อมูลที่ใช้สอนโมเดล)
    trainset = datasets.CIFAR10("./data", train=True, download=not data_exists, transform=transform)
    
    # ----------------------------------------------------
    # ☠️ ตรรกะการสลับป้ายกำกับ (Label Flipping Logic)
    # CIFAR-10 Classes: 3 = แมว (Cat), 5 = หมา (Dog)
    # ----------------------------------------------------
    poisoned_labels = []
    poison_count = 0
    
    for label in trainset.targets:
        if label == 3:  # ถ้าเจอรูปแมว
            poisoned_labels.append(5)  # แอบเปลี่ยนป้ายกำกับเป็น "หมา"
            poison_count += 1
        else:
            poisoned_labels.append(label) # รูปอื่นๆ ปล่อยไว้เหมือนเดิม
            
    # นำ Label ที่วางยาแล้ว ไปใส่ทับ Label เดิมใน Dataset
    trainset.targets = poisoned_labels
    print(f"☠️ วางยาข้อมูลสำเร็จ! เปลี่ยนรูปแมวเป็นหมาจำนวน {poison_count} รูป")
    # ----------------------------------------------------
    
    # โหลดข้อมูล Test (ฝั่ง Client ไม่จำเป็นต้องวางยาข้อมูล Test)
    testset = datasets.CIFAR10("./data", train=False, download=not data_exists, transform=transform)
    
    trainloader = DataLoader(trainset, batch_size=32, shuffle=True)
    testloader = DataLoader(testset, batch_size=32)
    return trainloader, testloader

def train(net, trainloader, epochs):
    """ฝึกสอนโมเดลด้วยข้อมูลในเครื่องตัวเอง"""
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(net.parameters(), lr=0.001, momentum=0.9)
    net.train()
    for _ in range(epochs):
        for images, labels in trainloader:
            optimizer.zero_grad()
            criterion(net(images), labels).backward()
            optimizer.step()

def test(net, testloader):
    """ทดสอบความแม่นยำของโมเดล"""
    criterion = torch.nn.CrossEntropyLoss()
    correct, total, loss = 0, 0, 0.0
    net.eval()
    with torch.no_grad():
        for images, labels in testloader:
            outputs = net(images)
            loss += criterion(outputs, labels).item()
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    accuracy = correct / total
    return loss, accuracy

# ==========================================
# 3. สร้าง Flower Client (เชื่อม PyTorch เข้ากับ FL)
# ==========================================
class FlowerClient(fl.client.NumPyClient):
    def __init__(self, net, trainloader, testloader):
        self.net = net
        self.trainloader = trainloader
        self.testloader = testloader

    def get_parameters(self, config):
        return [val.cpu().numpy() for _, val in self.net.state_dict().items()]

    def set_parameters(self, parameters):
        params_dict = zip(self.net.state_dict().keys(), parameters)
        state_dict = {k: torch.tensor(v) for k, v in params_dict}
        self.net.load_state_dict(state_dict, strict=True)

    def fit(self, parameters, config):
        self.set_parameters(parameters)
        train(self.net, self.trainloader, epochs=1)
        return self.get_parameters(config={}), len(self.trainloader.dataset), {}

    def evaluate(self, parameters, config):
        self.set_parameters(parameters)
        loss, accuracy = test(self.net, self.testloader)
        return float(loss), len(self.testloader.dataset), {"accuracy": float(accuracy)}

# ==========================================
# 4. เริ่มทำงาน (Start Client)
# ==========================================
if __name__ == "__main__":
    # 1. โหลดข้อมูลแบบวางยาและโมเดล
    net = SimpleCNN()
    trainloader, testloader = load_poisoned_data()
    
    # 2. เริ่มเชื่อมต่อกับ Server
    print("☠️ เริ่มต้นโหนดผู้ร้าย (Malicious Client)... กำลังป่วนระบบ!")
    fl.client.start_numpy_client(
        server_address="127.0.0.1:9090", 
        client=FlowerClient(net, trainloader, testloader)
    )
