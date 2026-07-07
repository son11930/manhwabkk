# 🚀 MANHWA.THAI - VPS Deployment Runbook & Operational Guide

คู่มือฉบับนี้เป็นขั้นตอนมาตรฐานสำหรับการนำระบบแปลมังฮวาและมังฮัว AI ขึ้นติดตั้งและเปิดใช้งานจริงบนเซิร์ฟเวอร์ VPS (เช่น DigitalOcean, AWS EC2, Linode, Google Cloud Compute) พร้อมระบบความปลอดภัยและการจัดการโฆษณาเพื่อสร้างรายได้

---

## 📋 1. ความต้องการของระบบเซิร์ฟเวอร์ (VPS Specifications)
- **OS:** Ubuntu 22.04 LTS / 24.04 LTS (x86_64)
- **CPU:** ขั้นต่ำ 2 vCPU (แนะนำ 4 vCPU สำหรับการทำงานประมวลผล Pillow ภาพความละเอียดสูงพร้อมกันหลายตอน)
- **RAM:** ขั้นต่ำ 2 GB (แนะนำ 4 GB)
- **Storage:** 20 GB SSD/NVMe ขึ้นไป (ระบบใช้เก็บฐานข้อมูล SQLite และ Log พื้นที่หลักของรูปภาพอยู่ที่ Cloudflare R2 ซึ่งฟรีและไม่กินพื้นที่ VPS)

---

## 🛠️ 2. ขั้นตอนการเตรียมเครื่องเซิร์ฟเวอร์ (Server Setup)

### 2.1 อัปเดตระบบและติดตั้ง Python, Node.js, Nginx & PM2
เชื่อมต่อเข้าสู่เซิร์ฟเวอร์ด้วย SSH จากนั้นรันคำสั่ง:
```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git curl ufw nginx python3.11 python3.11-venv python3-pip

# ติดตั้ง Node.js 20 LTS และ PM2 (Process Manager สำหรับควบคุมระบบไม่ให้ล่ม)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g pm2
```
*(หมายเหตุ: ระบบมาพร้อมไฟล์ฟอนต์การ์ตูนไทยมาตรฐาน Google TrueType ในโฟลเดอร์ `backend/assets/fonts/` แล้ว ทำให้รับประกันความสวยงาม 100% โดยไม่ต้องลงฟอนต์ OS เพิ่มเติม)*

### 2.2 ตั้งค่าความปลอดภัย Firewall (UFW)
```bash
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP
sudo ufw allow 443/tcp     # HTTPS
sudo ufw enable
```

---

## 📦 3. การติดตั้งโปรเจกต์และเปิดระบบ (Native Deployment Workflow)

### 3.1 โคลนซอร์สโค้ดลงเซิร์ฟเวอร์
```bash
git clone https://github.com/your-username/manhwabkk.git /opt/manhwabkk
cd /opt/manhwabkk
```

### 3.2 ตั้งค่าตัวแปรระบบ (.env)
คัดลอกไฟล์ตัวอย่างและใส่ค่าคีย์ลับของคุณ (Cloudflare R2 และ Groq API Key):
```bash
cp .env.example .env
nano .env
```
ตรวจสอบและกรอกค่าที่สำคัญดังนี้:
- `R2_ACCOUNT_ID`: รหัส Account ID จาก Cloudflare
- `R2_ACCESS_KEY_ID`: Access Key ที่สร้างจาก Cloudflare API Tokens
- `R2_SECRET_ACCESS_KEY`: Secret Key
- `R2_BUCKET_NAME`: `manga-bkk`
- `R2_DEV_URL`: ลิงก์ Public Dev URL ของ R2 Bucket
- `GROQ_API_KEY`: API Key สำหรับ Llama 3.3 70B
- `SUPER_ADMIN_EMAIL`: อีเมลสำหรับผู้ดูแลระบบ (สำหรับลบมังฮวา)
- `SUPER_ADMIN_PASSWORD`: รหัสผ่านที่คาดเดายาก (อย่างน้อย 12 ตัวอักษร)

### 3.3 ติดตั้งไลบรารีและเปิดเซิร์ฟเวอร์หลังบ้าน (Backend API ด้วย PM2)
```bash
cd /opt/manhwabkk/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# สั่งรัน Backend ด้วย PM2
pm2 start ".venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8000" --name manhwa-api
pm2 save
pm2 startup
```

### 3.4 บิลด์ระบบหน้าบ้าน (Frontend React Vite)
```bash
cd /opt/manhwabkk/frontend
npm install
npm run build
```
*(ไฟล์เว็บไซต์สำเร็จรูปจะถูกสร้างไว้ที่โฟลเดอร์ `/opt/manhwabkk/frontend/dist`)*

---

## 🌐 4. การเชื่อมต่อโดเมนและ Nginx Reverse Proxy

1. ชี้ DNS A Record ของโดเมนคุณ (เช่น `manhwa.in.th`) มาที่ IP ของ VPS
2. เปิดใช้งาน **Cloudflare Proxy (สัญลักษณ์เมฆสีส้ม)** เพื่อรับคุณสมบัติ DDoS Protection และ SSL ฟรี
3. ตั้งค่า Nginx สำหรับเสิร์ฟไฟล์หน้าบ้าน และส่งต่อ API:
```bash
sudo nano /etc/nginx/sites-available/manhwa
```
ใส่ค่าคอนฟิกดังนี้:
```nginx
server {
    listen 80;
    server_name manhwa.in.th www.manhwa.in.th;

    # เสิร์ฟหน้าเว็บ React (SPA)
    root /opt/manhwabkk/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # ส่งต่อ API ไปยัง FastAPI Backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8000;
    }
}
```
เปิดใช้งานเว็บและรีสตาร์ท Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/manhwa /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 🔄 5. วิธีอัปเดตโค้ดเวอร์ชันใหม่ในอนาคต (1-Click Update ด้วย Git Pull)
เมื่อมีการแก้ไขโค้ดหรือเพิ่มฟีเจอร์ใหม่ สามารถสั่งอัปเดตบนเซิร์ฟเวอร์ได้ง่ายๆ เพียงพิมพ์ 3 คำสั่งนี้:
```bash
cd /opt/manhwabkk
git pull
cd frontend && npm run build
pm2 restart manhwa-api
```

---

## 💰 5. การจัดการโฆษณาเพื่อสร้างรายได้ (Monetization Setup)

ระบบได้รับการออกแบบโครงสร้างป้ายโฆษณา (`AdSlot`) ไว้เรียบร้อยแล้วในตำแหน่งที่ไม่รบกวนผู้อ่าน:
- **Top Banner:** ด้านบนก่อนเริ่มอ่าน
- **In-between Banner:** แทรกระหว่างหน้าทุกๆ 2 หน้า
- **Bottom Banner:** ด้านล่างสุดข้างปุ่มเปลี่ยนตอน

### วิธีเปลี่ยนป้ายโฆษณาเป็นของจริง (Google AdSense หรือ Direct Sponsor)
เข้าไปแก้ไขที่ไฟล์ `frontend/src/components/AdSlot.tsx` โดยนำแท็กโค้ดจากเครือข่ายโฆษณามาใส่แทนที่ Mock Placeholder ได้ทันที

---

## 🔒 6. ความปลอดภัยและการดูแลรักษา (Security & Maintenance)

- **Super Admin Restriction:** ระบบหลังบ้านมีมาตรการตรวจสอบ `require_super_admin` ป้องกันผู้ไม่หวังดีลบรูปภาพหรือเรื่องออกเด็ดขาด
- **Immutable Cache R2:** รูปภาพมังฮวาที่ถูกแปลแล้วจะถูกอัปโหลดขึ้น Cloudflare R2 พร้อมตั้งค่า Cache Control ถาวร ทำให้เมื่อผู้ใช้คนแรกสั่งแปลเสร็จ คนต่อๆ ไปอ่านได้ทันทีโดยไม่เสียโควต้า AI และโหลดภาพไวสุดๆ จาก CDN ทั่วโลก
- **การสำรองข้อมูล (Backup):** ฐานข้อมูล SQLite เก็บอยู่ที่ `backend/manga_app.db` สามารถตั้ง Cron Job สำรองไฟล์นี้ไปที่ R2 ได้ทุกวันโดยไม่ต้องกังวลเรื่องระบบล่ม
