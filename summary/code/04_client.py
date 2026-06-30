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
# 2. ฟังก์ชันโหลดข้อมูล และเทรนโมเดล (PyTorch ปกติ)
# ==========================================
def load_data():
    """โหลดชุดข้อมูล CIFAR-10"""
    import os
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])
    # ตรวจสอบว่ามีข้อมูลแล้วหรือยัง เพื่อป้องกัน race condition ตอน download พร้อมกัน
    data_exists = os.path.exists("./data/cifar-10-batches-py")
    trainset = datasets.CIFAR10("./data", train=True, download=not data_exists, transform=transform)
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
        """ดึงค่าน้ำหนัก (Weights) จากโมเดล PyTorch เพื่อส่งให้ Server"""
        return [val.cpu().numpy() for _, val in self.net.state_dict().items()]

    def set_parameters(self, parameters):
        """รับค่าน้ำหนักที่ Server อัปเดตแล้ว มาใส่ในโมเดลตัวเอง"""
        params_dict = zip(self.net.state_dict().keys(), parameters)
        state_dict = {k: torch.tensor(v) for k, v in params_dict}
        self.net.load_state_dict(state_dict, strict=True)

    def fit(self, parameters, config):
        """กระบวนการเทรนเมื่อ Server สั่งมา"""
        self.set_parameters(parameters) # 1. รับน้ำหนักส่วนกลางมา
        train(self.net, self.trainloader, epochs=1) # 2. เทรนด้วยข้อมูลตัวเอง 1 รอบ
        return self.get_parameters(config={}), len(self.trainloader.dataset), {} # 3. ส่งน้ำหนักใหม่กลับไป

    def evaluate(self, parameters, config):
        """กระบวนการทดสอบเมื่อ Server สั่งมา"""
        self.set_parameters(parameters)
        loss, accuracy = test(self.net, self.testloader)
        return float(loss), len(self.testloader.dataset), {"accuracy": float(accuracy)}

# ==========================================
# 4. เริ่มทำงาน (Start Client)
# ==========================================
if __name__ == "__main__":
    # 1. โหลดข้อมูลและโมเดล
    net = SimpleCNN()
    trainloader, testloader = load_data()
    
    # 2. เริ่มเชื่อมต่อกับ Server ที่รันอยู่ในเครื่องเดียวกัน (localhost)
    print("🚀 เริ่มต้นโหนดลูก (Client)... กำลังรอเชื่อมต่อกับเซิร์ฟเวอร์")
    fl.client.start_numpy_client(
        server_address="127.0.0.1:9090", 
        client=FlowerClient(net, trainloader, testloader)
    )
