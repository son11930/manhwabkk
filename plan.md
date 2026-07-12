# แผนแก้ DeepSeek จากผล Log Chapter 149

## สรุปผลที่วัดได้

งาน 20 หน้าใช้เวลารวมประมาณ **274 วินาที (4 นาที 34 วินาที)** และจบด้วย `COMPLETED_WITH_WARNINGS`

| ช่วงงาน | เวลาจาก log | ข้อสังเกต |
|---|---:|---|
| Scrape/ดาวน์โหลด 20 หน้า | ~2 วินาที | ปกติ ไม่ใช่คอขวด |
| OCR | 32.47 วินาที | ~1.62 วินาที/หน้า ยอมรับได้ |
| Primary DeepSeek translation | 126.27 วินาที | คอขวดหลัก; สำเร็จเพียง 33 segments จาก 4 batches |
| Recovery + render/upload | 112.97 วินาที | recovery รายหน้าแบบต่อคิวกินเวลาส่วนใหญ่; render/upload จริง ~10 วินาที |

หลักฐานสำคัญ:

- Batch 1 และ Batch 3 ล้มเหลวทั้งรอบแรกและ retry แม้ HTTP จะตอบ `200 OK`
- Batch 2 สำเร็จ 24 segments ใน 21.63 วินาที และ Batch 4 สำเร็จ 9 segments ใน 6.83 วินาที
- ระบบทิ้งผลของ batch ที่ไม่ครบทั้งก้อน ทำให้ต้อง recovery หน้า 1–5 และ 11–15 ใหม่
- Recovery ถูกยิงทีละหน้าอย่างน้อย 10 requests จึงเพิ่มเวลาอีกประมาณ 88 วินาที
- ปัญหาไม่ใช่ quota/HTTP 429 แต่เป็น response contract/ผลลัพธ์ไม่ครบหรือ parse ไม่ผ่าน

## เป้าหมาย

- ลดเวลารวมจาก ~274 วินาทีเหลือไม่เกิน **110 วินาที** ใน fixture เดิม
- ลด Stage 2 + recovery จาก ~239 วินาทีเหลือไม่เกิน **75 วินาที**
- เก็บคำแปลที่ถูกต้องจาก response บางส่วนไว้ ห้ามส่งซ้ำโดยไม่จำเป็น
- แปลครบทุก expected ID หรือระบุ `NEEDS_REVIEW` ชัดเจน ห้าม publish ภาษาอังกฤษแบบเงียบ ๆ
- DeepSeek retry ภายใน provider และ model ที่ผู้ใช้เลือกเท่านั้น ห้ามข้ามไป Groq หรือ DeepSeek รุ่นอื่น
- รักษา glossary, ตัวละคร, เพศ และบริบทข้ามหน้า

## P0: เก็บ Partial Result และ Retry เฉพาะ ID ที่ขาด

1. เปลี่ยนผล parse จากผ่าน/ล้มทั้ง batch เป็น structured result:
   - valid translations
   - missing IDs
   - duplicate IDs
   - unknown IDs
   - malformed/parse error
   - token/model/latency metadata
2. เก็บ valid translations ลง chapter result map ทันที แม้ response จะไม่ครบ
3. Retry เฉพาะ missing/invalid IDs โดยใช้ DeepSeek provider/model เดิม
4. ไม่ส่ง ID ที่ผ่านแล้วซ้ำ เพื่อลดเวลา token และค่าใช้จ่าย
5. ถ้าคำแปลมี English leakage หรือผิด contract ให้เข้าคิว repair โดยไม่ทำลายผลลัพธ์อื่น

### Tests

- Response 30 IDs แต่ถูกต้อง 24 IDs ต้องเก็บ 24 และ retry เพียง 6
- JSON ส่วนท้ายเสียแต่มี entry ที่ parse ได้ ต้องเก็บ entry ที่ตรวจสอบได้
- unknown/duplicate IDs ต้องไม่เขียนทับ expected ID แบบไม่ชัดเจน
- ยืนยันว่าไม่มี Groq/โมเดลอื่นถูกเรียกจาก DeepSeek lane

## P1: Adaptive Split เมื่อ Batch ยังล้ม

1. หาก missing-only retry ยัง timeout, malformed หรือไม่ครบ ให้แบ่งเฉพาะ unresolved subset ครึ่งหนึ่ง
2. แบ่งตาม page/reading order และรักษา segment identity เดิม
3. ทำ recursive split แบบมีเพดาน depth/attempt ต่อ ID
4. ห้าม resend ID ที่สำเร็จแล้ว
5. เมื่อเหลือหนึ่ง ID แล้วยังล้ม ให้บันทึก `NEEDS_REVIEW` พร้อม issue code และหยุด retry storm
6. คำนวณ request budget จากจำนวน segments/chars/estimated output tokens ก่อนส่ง

### Tests

- bad segment 1 ตัวใน batch 5 หน้า ต้องทำให้ split เฉพาะส่วนที่เสีย
- ทุก retry ต้องมี provider/model เดิม
- split ต้อง terminate ตาม attempt budget
- ไม่มี ID หาย ซ้ำ หรือเปลี่ยน reading order

## P2: รวม Recovery Queue และทำพร้อมกันแบบจำกัด

1. เลิก recovery ทีละหน้าตาม loop ปัจจุบัน
2. รวม missing/QC-failed segments เป็น recovery queue หลัง primary wave
3. group ตาม page proximity และ token budget เพื่อรักษาบริบท
4. รัน recovery groups พร้อมกันโดยใช้ provider-local semaphore:
   - Flash เริ่ม canary ที่ 3 concurrent recovery requests
   - Pro แยก config และเริ่มค่าต่ำกว่า Flash
5. merge ผลกลับตาม page index/reading order แบบ deterministic
6. รองรับ `Retry-After`, jittered backoff และ shared provider limiter

### Tests

- 10 หน้าที่ล้มต้อง recovery เป็น bounded waves ไม่ใช่ 10 calls ต่อคิว
- ตรวจ max in-flight, ordered merge และ context snapshot เดียวกัน
- 429 ต้อง backoff โดยไม่สร้าง retry storm

## P3: รักษา Context/เพศโดยไม่บังคับทุก Batch ต่อคิว

1. สร้าง `chapter context snapshot` ก่อน primary translation จาก OCR ทั้งตอน:
   - character names/aliases
   - gender evidence และ relationship เช่น sister/brother
   - glossary/ranks
   - concise source context รอบหน้าข้างเคียง
2. ส่ง snapshot เดียวกันให้ทุก primary/recovery batch
3. กลับมาใช้ primary translation แบบ bounded waves เพื่อเอาความเร็วคืน:
   - Flash canary เริ่ม 2 batches พร้อมกัน
   - Pro ใช้ config แยก
4. หลัง wave จบ ให้ commit approved context แล้วส่งไป wave ถัดไป
5. ถ้าการ์ตูนเรื่องใดต้องการ translated-context แบบเข้ม ให้เปิด sequential/checkpoint mode เป็นราย title ไม่ใช้บังคับทุกงาน

แนวทางนี้รักษาข้อมูลเพศและตัวละครแบบ chapter-global ขณะยังยิง batch พร้อมกันได้บางส่วน

## P4: Overlap Render/Upload กับ Recovery

1. เมื่อหน้าหนึ่งผ่าน QC ครบ ให้ enqueue render/upload ได้ทันที
2. หน้าอื่นสามารถ recovery ต่อพร้อมกัน โดยใช้ AI/CPU/upload semaphore แยกกัน
3. การ publish chapter ยังคง atomic: reader เห็นงานเมื่อสถานะสุดท้ายผ่านเท่านั้น
4. แยกเวลา translation recovery ออกจาก Stage 3 เพื่อไม่ให้ metric render ดูช้ากว่าความจริง

## Observability ที่ต้องเพิ่มก่อนปรับ Algorithm

ทุก request ต้องมี `run_id`, `batch_id`, `attempt`, `split_parent` และบันทึกแบบ structured โดยไม่เก็บ secret/full dialogue:

- expected/valid/missing/duplicate/unknown ID counts
- page/segment/character count และ estimated tokens
- queue/API/parse/QC/recovery/render/upload duration
- provider/model, HTTP status, timeout/429, finish reason และ retry reason
- initial coverage, final coverage, resend ratio, retry tokens/cost
- warning issue codes และ unresolved IDs

ต้องแสดง critical-path wall time แยกจากผลรวม request time เพื่อระบุคอขวดถูกจุด

## Acceptance Criteria

- expected-ID accounting = 100%
- translated coverage = 100% หรือ unresolved ทุกตัวเป็น `NEEDS_REVIEW`
- zero silent source-text publication
- valid partial results ไม่ถูก resend
- resend ratio ไม่เกิน 20% ใน failure pattern ของ log นี้
- Stage 2 + recovery ไม่เกิน 75 วินาที
- รวมทั้งตอนไม่เกิน 110 วินาที
- render/upload ไม่เกิน 15 วินาทีและ overlap กับ recovery
- glossary/entity/gender accuracy อย่างน้อย 99%
- quality/context score ลดจาก baseline ไม่เกิน 1 percentage point
- 429 ไม่เกิน 1% และค่าใช้จ่ายไม่เพิ่มเกิน 5% จาก clean run
- ไม่มี cross-provider หรือ cross-model fallback

## ลำดับการลงมือ

1. เพิ่ม observability และ replay fixture จาก run นี้
2. ทำ partial-preserving parser + missing-only recovery
3. ทำ adaptive split พร้อม attempt budget
4. รวม concurrent recovery queue
5. ทำ chapter context snapshot + primary checkpoint waves
6. overlap render/upload
7. benchmark 5/8/10 pages หลัง failure/recovery path เสถียรแล้ว

## Rollout/Rollback

- แยก feature flags: partial parser, adaptive split, recovery concurrency, primary wave concurrency
- เปิดตามลำดับ: tests/replay → shadow → canary 10% → 50% → 100%
- งานที่กำลังทำใช้ policy snapshot เดิมจนจบ
- rollback flag ล่าสุดเมื่อ completeness/quality ลด, 429 > 1%, cost > 5% หรือ p95 latency แย่กว่า control > 10%

## Handoff

แผนพร้อมให้โมเดล implementation ทำแบบ TDD โดยเริ่ม P0 ก่อน ห้ามเริ่มจากเพิ่ม concurrency เพราะต้นเหตุหลักคือการทิ้ง partial result และ recovery ซ้ำจำนวนมาก

---

# แผนเสริม: OCR ตัวอักษรเอียง/Italic จาก Fixtures ใน `img/`

## Failure Capture จากการรันจริง

Fixture ที่ใช้:

- `img/1.PNG`
- `img/2.PNG`

ผลจาก `MangaOCREngine.detect_and_extract_sync()` ปัจจุบัน:

| Fixture | ข้อความที่ควรอ่าน | OCR ปัจจุบัน |
|---|---|---|
| `1.PNG` | `LU SHU'S VOICE!!` | `SOHS 01` |
| `1.PNG` | `LU SHU, PLEASE HELP ME TRANSLATE...` | `OHS 01 PLEASE HELP ME TRANSLAT...` |
| `1.PNG` | `EH, WHERE IS HE?` | `EH, WHERE` |
| `2.PNG` | `DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!` | `DON'T! IS THIRTY-FINE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE` |

ระบบตรวจเจอข้อความบางส่วน จึงไม่ใช่ปัญหา translation provider แต่เป็น OCR source ที่ผิด/ขาดก่อนส่งให้ AI

## Root Cause

1. ตัวอักษรใน fixture เป็น **italic/shear** แต่แนว baseline และ detection polygon เกือบนอนตรง
2. Recovery ปัจจุบันทำงานเฉพาะ polygon ที่มีมุม 2–20° จึงข้าม italic ที่ angle ใกล้ 0°
3. Recovery ตรวจเฉพาะ line ที่ confidence ต่ำกว่า 0.65:
   - `2.PNG` อ่านผิด `FINE` ด้วย confidence 0.797 จึงไม่ถูกตรวจใหม่
   - `EH, WHERE` confidence 0.859 แม้หาย `IS HE?` ก็ไม่ถูกตรวจใหม่
4. หากข้อความบางบรรทัดไม่ถูก detector สร้าง polygon ระบบไม่มี ROI สำหรับ deskew
5. Full-page enhanced pass ทำเฉพาะตอนทั้งหน้าไม่มี `lines`; ถ้าหน้ามีข้อความอื่นที่ตรวจเจอ ส่วนที่หายจะไม่เข้าสู่ recovery
6. การหมุน/rectify quadrilateral แก้ rotation และ perspective ได้ แต่ไม่ได้แก้ horizontal shear ของฟอนต์ italic

## เป้าหมาย

- Fixture ทั้งสองต้องได้ข้อความครบทุก clause และเครื่องหมายสำคัญ
- หลายบรรทัดใน speech bubble เดียวต้องรวมเป็น OCR segment เดียว
- box ต้องอยู่ภายใน speech bubble และห้ามขยายกินหลาย panel/หน้า
- หน้าปกติห้ามเสียเวลาเพิ่มเกิน 300 ms โดยเฉลี่ย
- หน้า affected ใช้ fallback เพิ่มได้ไม่เกิน 1.5 วินาที
- ห้ามใช้ AI เดาคำที่ OCR ไม่มีหลักฐานภาพรองรับ

## OCR-P0: สร้าง Golden Fixture Tests ก่อนแก้

1. Copy/reference fixture จาก `img/` เป็น test fixture โดยรักษาไฟล์ต้นฉบับไว้
2. เพิ่ม baseline test ที่ยืนยัน failure ปัจจุบันก่อน implementation
3. Expected text:
   - `LU SHU'S VOICE!!`
   - `LU SHU, PLEASE HELP ME TRANSLATE...`
   - `EH, WHERE IS HE?`
   - `DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!`
4. ทดสอบ clause coverage แยกจาก exact punctuation เพื่อไม่ให้ test เปราะเกินไป
5. ทดสอบ box containment, reading order, bubble grouping และห้าม duplicate overlay

## OCR-P1: Coverage Audit ที่ไม่พึ่ง Confidence อย่างเดียว

หลัง primary OCR ให้ตรวจ speech-bubble/text coverage:

1. หา candidate speech bubble จากพื้นที่สว่าง/contour/connected region โดยไม่ต้องรอ OCR polygon
2. ตรวจ dark text-like connected components ภายใน bubble
3. วัดสัดส่วน component ที่ไม่ถูก OCR boxes ครอบคลุม
4. Trigger recovery เมื่อ:
   - มี text-like components ที่ยัง uncovered
   - OCR box ครอบเฉพาะช่วงบนของกลุ่มบรรทัด
   - candidate text จบกลางประโยคหรือหายบรรทัดล่าง
   - ensemble disagreement สูง แม้ confidence เดิมสูง
5. Confidence ใช้เป็นหนึ่งใน evidence เท่านั้น ห้ามใช้ threshold 0.65 เป็นประตูเดียว

Coverage audit นี้ต้องจับ `IS HE?` และ `STONES!` ที่อยู่นอก box ปัจจุบันได้

## OCR-P2: Bubble-Crop Recognition ก่อน Full-Page Recovery

1. Crop เฉพาะ candidate bubble พร้อม padding จำกัด
2. Upscale crop แบบรักษาขอบตัวอักษร 2× ก่อนส่ง detector/recognizer ใหม่
3. คืนพิกัดจาก crop กลับสู่ page coordinates แบบ deterministic
4. จำกัดจำนวน candidate bubbles ต่อหน้าและ early-exit เมื่อ coverage ครบ
5. ใช้ full-page enhanced OCR เฉพาะเมื่อ bubble proposal ล้มเหลวทั้งหน้า

เหตุผล: การ crop ทำให้ตัวอักษร comic มีขนาดสัมพัทธ์ใหญ่ขึ้น และช่วย detector เห็นบรรทัดที่หลุดโดยไม่เพิ่ม CPU ทั้งหน้า

## OCR-P3: Bounded Transform Cascade สำหรับ Italic/Shear

สำหรับ bubble ที่ coverage ไม่ครบ ให้ทดลองตามลำดับและหยุดเมื่อได้ candidate ที่ผ่าน:

1. original crop + upscale
2. grayscale + CLAHE/contrast normalization
3. mild horizontal affine shear correction เช่น ±0.12 และ ±0.22
4. rotation ±3°/±6° เฉพาะเมื่อ baseline angle มีหลักฐาน
5. perspective rectify เฉพาะ quadrilateral ที่ผ่าน geometry validation

ห้าม brute-force หลายสิบมุมทั้งหน้า และจำกัด transform budget ต่อ bubble

## OCR-P4: Candidate Selection แบบ Evidence/Consensus

1. Normalize whitespace แต่รักษา apostrophe, hyphen, `!`, `?`, ellipsis และตัวเลข
2. เลือก candidate ด้วยคะแนนรวม:
   - OCR confidence
   - clause/character coverage
   - uncovered-component reduction
   - agreement อย่างน้อยสอง transforms
   - English word plausibility โดยไม่ hardcode เนื้อเรื่อง
3. Candidate ที่ยาวขึ้นต้องมี visual components รองรับ ห้ามเลือกเพราะข้อความยาวกว่าอย่างเดียว
4. ถ้า variants ขัดแย้งกันมาก ให้ `NEEDS_REVIEW` พร้อม diagnostic แทนการเดา
5. รวม line candidates ใน bubble เดียวก่อนส่ง translation เพื่อไม่ให้แปลแยกและวางทับกัน

## OCR-P5: Box และ Bubble Integrity

- Clamp box ให้อยู่ในภาพและ candidate bubble
- Reject box ที่ area ใหญ่เกินสัดส่วน bubble/page
- Merge เฉพาะ line ที่อยู่ใน bubble mask เดียวกันและมี reading order ต่อเนื่อง
- ป้องกัน bubble ข้างเคียงรวมกันจากระยะใกล้
- ส่ง bubble-level box เดียวให้ inpaint/typeset หลังยืนยันข้อความครบ

## Observability

บันทึกต่อ candidate โดยไม่เก็บภาพหรือข้อความเต็มใน production log:

- fixture/page/bubble ID
- primary text length/confidence/box coverage
- uncovered component count/ratio
- recovery trigger reason
- transforms attempted และ latency
- selected variant/score/consensus
- recovered line count และ unresolved reason

เพิ่ม debug artifact แบบ opt-in สำหรับ local/test เท่านั้น: bubble crop, component mask และ boxes ก่อน/หลัง recovery

## Acceptance Criteria

- `img/1.PNG` clause coverage ครบทั้ง 3 bubbles
- `img/2.PNG` ต้องได้ `THIRTY-FIVE` ทั้งสองตำแหน่งและ `STONES!`
- ไม่มี `SOHS 01`, `OHS 01`, `THIRTY-FINE` ใน final OCR
- ไม่มี line สำคัญหลุดก่อน translation
- bubble-level grouping ไม่สร้างข้อความซ้อนหรือ box ขนาดผิดปกติ
- clean-page OCR latency เพิ่มไม่เกิน 300 ms โดยเฉลี่ย
- affected-page fallback เพิ่มไม่เกิน 1.5 วินาที
- existing OCR/translation tests และ golden fixtures ผ่านทั้งหมด

## ลำดับการทำร่วมกับแผน DeepSeek

1. ทำ OCR-P0 fixture tests และ DeepSeek P0 observability ก่อน
2. ทำ OCR coverage audit + bubble crop recovery
3. ทำ DeepSeek partial-preserving parser/missing-only recovery
4. เพิ่ม bounded shear transform และ candidate consensus
5. ทำ adaptive split/concurrent DeepSeek recovery
6. ทดสอบ Chapter 149 end-to-end: OCR source completeness → translation completeness → box integrity → latency

## Handoff

รอบ implementation ต้องเริ่มจาก fixture tests ใน `img/` และพิสูจน์ว่า baseline ล้มตามที่บันทึกไว้ ห้ามเริ่มจากเพิ่ม rotation angles อย่างเดียว เพราะตัวอย่างนี้เป็น shear/italic และมี missing detection regions ไม่ใช่ baseline rotation อย่างเดียว
