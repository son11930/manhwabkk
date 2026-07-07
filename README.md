# 🚀 MANHWA.THAI — AI Manga & Manhua Translation Platform

![Version](https://img.shields.io/badge/version-1.0.0--MVP-cyan.svg)
![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![React](https://img.shields.io/badge/React-18%20%7C%20Vite-61DAFB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC.svg)
![Cloudflare R2](https://img.shields.io/badge/Cloudflare-R2_CDN-F38020.svg)
![Groq AI](https://img.shields.io/badge/Groq-Llama_3.3_70B-8A2BE2.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**ระบบแปลมังฮวาและมังฮัวจากภาษาอังกฤษเป็นภาษาไทยแบบเรียลไทม์ (AI-Powered Webtoon Translator Platform)**  
พัฒนาภายใต้สถาปัตยกรรม **Everything Claude Code (ECC)** เน้นความลื่นไหล ภาษาการแปลที่เป็นธรรมชาติเหมือนคนแปลจริงๆ พร้อมระบบสร้างรายได้สนับสนุนเซิร์ฟเวอร์ และการจัดการฟอนต์ภาษาไทยแบบฝังตัว (Embedded TrueType Font) รับประกันความสวยงามไม่เพี้ยนในทุกแพลตฟอร์ม

---

## ✨ Features (คุณสมบัติเด่น)

- 🧠 **AI Translator Engine (Groq Llama 3.3 70B):** แปลภาษาไทยด้วยสำนวนสไตล์ Webtoon อ่านรู้เรื่อง ลื่นไหล มีความอินกับอารมณ์ตัวละคร ไม่แข็งกระด้างเหมือนกูเกิลแปลภาษา
- 🖼️ **Vision Typesetter & Embedded TrueType Fonts:** ถมพื้นหลังคำพูดและวาดข้อความภาษาไทยลงไปใน Speech Bubble โดยใช้ฟอนต์ **Prompt** และ **Sarabun** ที่ฝังมากับโปรเจกต์ (100% Guaranteed No Box Characters `□□□`)
- ☁️ **Cloudflare R2 Immutable Cache:** รูปภาพที่ผ่านการแปลแล้วจะถูกอัปโหลดเก็บไว้บน CDN คลาวด์ฟรี โหลดภาพเร็วทันใจและไม่เปลืองโควต้า AI ซ้ำซ้อน
- 📱 **Mobile-First Vertical Webtoon Reader:** หน้าต่างอ่านการ์ตูนออกแบบมาเพื่อโทรศัพท์มือถือและคอมพิวเตอร์ เลื่อนแนวดิ่งต่อเนื่องไม่มีขอบขาวขวางหน้าจอ พร้อมปุ่มเปลี่ยนตอนอัตโนมัติ
- 💰 **Non-intrusive Ad Slots:** ระบบป้ายโฆษณา (Top, Bottom, Sidebar และ Inter-page ทุกๆ 2 หน้า) ออกแบบมาเพื่อสร้างรายได้สนับสนุนเซิร์ฟเวอร์โดยไม่รบกวนการอ่าน
- 🔒 **Super Admin Security Guard:** ระบบหลังบ้านพร้อมสิทธิ์การตรวจสอบ JWT Auth ไม่อนุญาตให้บุคคลภายนอกกดลบตอนหรือเรื่องออกเด็ดขาด โดยเมื่อสั่งลบระบบจะลบภาพทั้งหมดออกจาก Cloudflare R2 ทันทีเพื่อประหยัดพื้นที่

---

## 🛠️ Technology Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (Asyncio), SQLite / PostgreSQL, Pillow, BeautifulSoup4, HTTPX, Pydantic v2
- **Frontend:** TypeScript, React 18, Vite 5, Tailwind CSS, Lucide Icons, React Router DOM
- **AI & Storage:** Groq API (`llama-3.3-70b-versatile`), Cloudflare R2 Object Storage (S3 Compatible)

---

## 🚀 Quick Start (วิธีเปิดใช้งานระบบในคลิกเดียว สำหรับ Windows)

โปรเจกต์นี้มาพร้อมระบบสคริปต์อัตโนมัติ ไม่ต้องสั่งคำสั่ง Terminal เองให้ยุ่งยาก!

1. **คัดลอกไฟล์ `.env.example` เป็น `.env`** แล้วใส่ค่า API Key ของคุณ:
   ```env
   R2_ACCOUNT_ID=your_account_id
   R2_ACCESS_KEY_ID=your_access_key
   R2_SECRET_ACCESS_KEY=your_secret_key
   R2_BUCKET_NAME=manga-bkk
   R2_DEV_URL=https://pub-xxxxxx.r2.dev
   GROQ_API_KEY=gsk_xxxxxx
   SUPER_ADMIN_EMAIL=admin@manhwabkk.local
   SUPER_ADMIN_PASSWORD=supersecurepassword123!
   ```
2. **ดับเบิลคลิกไฟล์ `start_app.bat`**: ระบบจะทำการเปิดเซิร์ฟเวอร์หลังบ้าน (Port 8000) และหน้าบ้าน (Port 5173) พร้อมเปิดเบราว์เซอร์พาเข้าสู่เว็บอ่านการ์ตูนทันที!
3. **การอัปเดตโค้ดในอนาคต:** ดับเบิลคลิกไฟล์ `update_app.bat` เพื่อทำการ `git pull` และบิลด์ระบบใหม่ในคลิกเดียว

---

## 📖 VPS Production Deployment

สำหรับการนำระบบขึ้นเซิร์ฟเวอร์จริง (Linux VPS Ubuntu / Debian) ด้วย **PM2 + Nginx (Native Setup - No Docker Required)** สามารถอ่านขั้นตอนและ Runbook โดยละเอียดได้ที่ไฟล์ [DEPLOYMENT_RUNBOOK.md](file:///e:/Code/manhwabkk/DEPLOYMENT_RUNBOOK.md)

---

## 👨‍💻 Author & Maintainer

- **Developer:** son11930
- **Email:** son11930@hotmail.com
- **GitHub Repository:** [https://github.com/son11930/manhwabkk](https://github.com/son11930/manhwabkk)
