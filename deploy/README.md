# QoR Recorder - Linux 部署指南

## 1. 系统要求

- Python 3.9+
- 512MB 内存 (最低)
- Linux (Ubuntu/Debian/CentOS/RHEL 均可)

## 2. 快速部署

```bash
# 克隆代码
cd /opt
git clone <your-repo> qor_recorder
cd qor_recorder

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
vim .env  # 修改 PORT, SECRET_KEY, DATABASE_URL 等

# 初始化数据库
python init_db.py --demo  # 加演示数据

# 启动
./start.sh
# 或: PORT=1344 ./start.sh
```

## 3. 使用自定义主机名 (如 local.feint:1344)

```bash
# 修改 /etc/hosts (需 root)
echo "127.0.0.1 local.feint" | sudo tee -a /etc/hosts

# 配置 .env
echo "PORT=1344" >> .env

# 启动后即可访问
curl http://local.feint:1344/
```

## 4. 生产部署 (systemd 服务)

```bash
# 复制 service 文件
sudo cp deploy/qor_recorder.service /etc/systemd/system/

# 修改其中的路径和用户
sudo vim /etc/systemd/system/qor_recorder.service

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable qor_recorder
sudo systemctl start qor_recorder

# 查看状态
sudo systemctl status qor_recorder
sudo journalctl -u qor_recorder -f  # 实时日志
```

## 5. 使用 Nginx 反向代理 (推荐生产环境)

```nginx
server {
    listen 80;
    server_name qor.example.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 上传文件大小限制
    client_max_body_size 32M;
}
```

## 6. 使用 MySQL (多用户高并发场景)

```bash
# 1. 安装 MySQL
sudo apt install mysql-server

# 2. 创建数据库和用户
sudo mysql <<EOF
CREATE DATABASE qor_recorder CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'qor'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON qor_recorder.* TO 'qor'@'localhost';
FLUSH PRIVILEGES;
EOF

# 3. 配置 .env
echo 'DATABASE_URL=mysql+pymysql://qor:your_password@localhost:3306/qor_recorder?charset=utf8mb4' >> .env

# 4. 初始化
python init_db.py
```

## 7. 数据备份

```bash
# SQLite
cp qor_recorder.db backups/qor_$(date +%Y%m%d).db

# MySQL
mysqldump -u qor -p qor_recorder > backups/qor_$(date +%Y%m%d).sql

# 自动备份 (crontab)
echo "0 2 * * * cd /opt/qor_recorder && cp qor_recorder.db backups/qor_$(date +\%Y\%m\%d).db" | crontab -
```

## 8. 升级

```bash
cd /opt/qor_recorder
git pull
source venv/bin/activate
pip install -r requirements.txt

# 数据库迁移
flask db upgrade

# 重启服务
sudo systemctl restart qor_recorder
```

## 9. DC 流程自动化集成

```bash
# 创建 API Key (登录 Web 界面或用 curl)
curl -X POST http://localhost:5000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 上传 QoR 数据
export QOR_API_KEY=qor_xxxxxxxx
export QOR_SERVER=http://localhost:5000
./scripts/upload_qor.sh 1 v1.0 qor_report.csv
```
