# Implementation Plan: Orientation-Aware OCR สำหรับข้อความการ์ตูนเอียง

## คำสั่งสำหรับโมเดลผู้ลงมือแก้

- แผนนี้ครอบคลุมเฉพาะปัญหา OCR ตัวอักษรอังกฤษเอียง/stylized จากภาพตัวอย่างล่าสุด
- ใช้ TDD: เขียน regression tests ให้ล้มก่อน แล้วจึงแก้ implementation
- ก่อนแก้โค้ดให้อัปเดต `PROJECT_PLAN.md`; เมื่อเสร็จให้อัปเดต `CHANGELOG.md` ตาม `RULES.md`
- ห้ามแก้ด้วยการให้ AI เดาคำจากบริบท หาก OCR evidence ยังไม่ชัดเจน
- ห้ามลดคุณภาพหรือเพิ่ม full-page OCR หลายรอบจน performance ถดถอย

## Problem

ตัวอักษรการ์ตูนมีความเอียง รูปทรงลายมือ ความกว้างไม่สม่ำเสมอ และมีเครื่องหมายสำคัญ เช่น apostrophe/hyphen ทำให้ OCR อ่าน source ผิดก่อนส่งให้ AI แปล

กรณีที่พบ:

1. `DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!`
   - OCR อาจอ่าน `THIRTY-FIVE` หรือตัวเลขผิด
   - ผลแปลปัจจุบันสร้าง `+777` ซึ่งไม่มีในภาพ
2. `LU SHU'S VOICE!! / LU SHU, PLEASE HELP ME TRANSLATE...`
   - OCR อาจอ่าน `LU SHU` เป็นกลุ่มตัวอักษรคล้าย `O1/01`
   - AI จึงถอดเสียงชื่อผิดและแปลความหมายไม่ครบ

Root cause อยู่ก่อน LLM: source text จาก OCR ผิดหรือไม่แน่นอน แต่ถูกส่งให้ provider เป็นข้อเท็จจริง

## Fixed Constraints

- OCR และ candidate selection เป็น provider-neutral; Groq และ DeepSeek ต้องได้รับ selected source text ชุดเดียวกัน
- AI provider ห้ามเลือกหรือแก้ OCR candidate เอง
- Groq สลับ model ได้เฉพาะภายใน Groq fallback hierarchy และห้ามข้ามไป DeepSeek
- DeepSeek ล็อก provider/model ที่ผู้ใช้เลือกตลอด initial request, retry, repair และ QC; ห้ามข้าม model/provider
- หาก OCR ยังไม่แน่นอน ให้ `NEEDS_REVIEW` แทนการเดาแล้ว publish
- ห้ามสร้างชื่อ ตัวเลข หรือข้อความที่ไม่มี image/OCR evidence

## Phase 1 — Baseline และ RED Tests

สร้าง fixture จาก crop จริงและ synthetic rotated text ที่มุม:

- `-15°`
- `-8°`
- `0°`
- `+8°`
- `+15°`

เก็บ baseline:

- OCR output และ confidence
- จำนวน OCR invocations ต่อ ROI/หน้า
- pixel count ที่ประมวลผล
- OCR wall time, CPU time และ peak RSS
- จำนวน `OCR_AMBIGUOUS_TEXT`
- จำนวนชื่อ/ตัวเลขที่ source-integrity gate จับได้

เขียน tests ให้ล้มก่อนสำหรับ:

- ข้อความเอียงถูกอ่านผิด แต่ deskew candidate อ่านถูก
- ข้อความแนวนอน confidence สูงไม่เข้า deskew recovery
- `LU SHU'S` ต้องรักษาชื่อและ apostrophe
- `THIRTY-FIVE` ต้องรักษาคำ/จำนวนครบสองตำแหน่ง
- candidate ที่สร้าง `O1`, `01` หรือ `777` ต้องไม่ถูกเลือกเมื่อไม่มี image evidence
- candidate คะแนนใกล้กันแต่ให้ชื่อ/ตัวเลขต่างกันต้องเป็น ambiguous

## Phase 2 — ตรวจมุมและ Deskew เฉพาะ ROI

- ประเมิน orientation ต่อ OCR line/ROI จาก detector polygon เป็นหลัก
- ใช้ contour/min-area rectangle หรือ text baseline estimation เป็น fallback
- normalize มุมให้อยู่ในช่วง `[-20°, +20°]`
- หากมุมเกินช่วงหรือหลักฐานไม่เสถียร ให้ `OCR_ORIENTATION_UNCERTAIN`
- Primary OCR ต้องใช้ภาพเดิมก่อนเสมอ
- เรียก deskew recovery เฉพาะเมื่อเข้าเงื่อนไขใดเงื่อนไขหนึ่ง:
  - confidence ต่ำกว่า threshold
  - polygon/text baseline เอียงเกิน threshold
  - character pattern ผิดปกติ
  - ชื่อ ตัวเลข apostrophe หรือ hyphen ไม่ผ่าน lexical evidence
- Crop เฉพาะ ROI พร้อม padding; ห้ามหมุนหรือ upscale ทั้งหน้า
- หมุนตาม estimated angle และมุมข้างเคียงเพียงเล็กน้อย เช่น `±2°`
- จำกัด recovery scale และ pixel budget; ห้าม brute-force หลายมุม
- inverse-map polygon/box กลับพิกัดภาพต้นฉบับก่อน grouping, inpaint และ typeset

## Phase 3 — Candidate Selection ด้วยหลักฐาน

เก็บ candidate จาก:

- original ROI
- deskewed ROI
- contrast-normalized deskewed ROI เมื่อจำเป็น

คำนวณ selection score จาก:

- OCR confidence
- ความถูกต้องของตัวอักษรอังกฤษ
- English word plausibility
- agreement ระหว่าง candidates
- punctuation preservation
- apostrophe/hyphen preservation
- line continuity และ reading order
- consistency ของชื่อและตัวเลขภายใน bubble

กฎสำคัญ:

- Dictionary/lexicon ใช้จัดอันดับหรือ flag เท่านั้น ห้าม rewrite source โดยไม่มี candidate จากภาพรองรับ
- ชื่อเฉพาะและจำนวนมีน้ำหนักสูงกว่าคำทั่วไป
- หาก top candidates คะแนนใกล้กันแต่ชื่อ/ตัวเลขต่างกัน ให้ `OCR_AMBIGUOUS_TEXT`
- ห้ามส่ง ambiguous candidate ให้ AI translation

OCR artifact ต้องเก็บ:

- `raw_candidate`
- `normalized_candidate`
- `angle`
- `transform`
- `confidence`
- `selection_score`
- `selection_reason`

## Phase 4 — Bubble และ Translation Contract

- หลาย OCR lines ใน bubble เดียวต้องรวมเป็น translation segment เดียวตาม reading order
- เก็บ line boxes แยกจาก bubble box
- Translation provider รับ selected `source_text` พร้อม source-integrity evidence
- Source-integrity gate ต้องตรวจ:
  - ตัวเลขต้นฉบับกับคำแปล
  - ชื่อเฉพาะ
  - rank/level
  - apostrophe/hyphen ที่มีผลต่อการอ่าน
- หากคำแปลเพิ่ม `+777`, `O1/01`, ชื่อ หรือจำนวนที่ไม่มีใน evidence ให้ reject และส่ง provider-locked repair
- หาก repair ยังไม่ผ่าน ให้ `NEEDS_REVIEW`; ห้าม publish ข้อความมั่ว

## Tests

### OCR Unit Tests

- Deskew มุม `-15°, -8°, +8°, +15°` แล้วอ่านข้อความตรงกับ fixture แนวนอน
- High-confidence horizontal ROI เรียก OCR ครั้งเดียว
- Recovery ทำเฉพาะ ROI และไม่เกิน invocation/pixel budget
- Inverse transform คืน coordinates เดิมภายใน tolerance
- Candidate selector เลือก `LU SHU'S VOICE!!` เหนือ candidate `O1/01`
- Candidate selector รักษา `THIRTY-FIVE` ครบสองตำแหน่ง
- Candidate ขัดกันเรื่องชื่อ/ตัวเลขได้ `OCR_AMBIGUOUS_TEXT`

### Integration Tests

- หลายบรรทัดใน bubble เดียวถูกส่ง provider เป็น segment เดียว
- DeepSeek repair ใช้ model/provider เดิมเท่านั้น
- Groq repair อยู่ภายใน Groq เท่านั้น
- Ambiguous OCR ไม่ถูกส่ง provider
- Source-integrity gate จับ `+777`, `O1`, `01` และชื่อที่ไม่มีใน source evidence
- Inpaint/typeset ใช้ coordinates ต้นฉบับ ไม่ใช้ coordinates หลังหมุน

### Performance Tests

- หน้าปกติไม่เรียก deskew recovery
- จำนวน OCR pixels ของหน้าปกติไม่เพิ่มจาก baseline
- หน้าที่มีข้อความเอียงยังอยู่ภายใน ROI/pixel budget
- OCR wall time ของ chapter ปกติไม่เกิน 110% ของ baseline ก่อนเพิ่มฟีเจอร์
- CPU และ peak RSS ไม่ถดถอยเกิน 15%

## Golden Regressions

### A. Thirty-Five Stones

Source:

`DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!`

ต้องผ่านเงื่อนไข:

- OCR รักษา `THIRTY-FIVE` ครบสองตำแหน่ง หรือ normalize เป็น `35` พร้อม evidence mapping
- คำแปลรักษาความหมายคำถามและคำสั่ง
- ห้ามสร้าง `+777` หรือตัวเลขอื่นที่ไม่มีในภาพ

### B. Lu Shu Voice

Source lines:

1. `LU SHU'S VOICE!!`
2. `LU SHU, PLEASE HELP ME TRANSLATE...`

ต้องผ่านเงื่อนไข:

- OCR รักษา `LU SHU`, apostrophe และลำดับบรรทัด
- สองบรรทัดอยู่ใน translation segment เดียว
- คำแปลรักษาทั้ง “เสียงของลู่ซู” และ “ลู่ซู ช่วยฉันแปลหน่อย”
- ห้ามเกิด `O1`, `01` หรือชื่อที่ไม่มีในภาพ

## Acceptance Criteria

- Golden regressions ทั้งสองผ่าน
- ข้อความเอียงที่รองรับถูกอ่านถูกโดยไม่เพิ่ม full-page OCR pass
- ไม่มี ambiguous OCR ถูกส่งให้ AI หรือ publish
- ไม่มีชื่อ/ตัวเลขที่ไม่มี evidence หลุดผ่าน final QC
- Groq/DeepSeek provider policy ไม่ถูกละเมิด
- Backend tests ผ่านและ touched-code coverage อย่างน้อย 80%
- Performance อยู่ภายใน CPU/RSS/wall-time budgets

## Handoff

พร้อมให้โมเดลตัวเล็กทำตามลำดับ: RED tests → ROI orientation detection → deskew/inverse transform → candidate scoring → source-integrity gate → integration/performance verification → `CHANGELOG.md`
