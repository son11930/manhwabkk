# แผนแก้ Stage 1 OCR ช้าลงหลังเพิ่มการกู้ตัวอักษรเอียง

## ขอบเขต

แผนนี้แก้เฉพาะ performance ของ Stage 1 โดยต้องรักษาความสามารถกู้ข้อความเอียงที่เพิ่มล่าสุดไว้ ยังไม่อนุญาตให้เปลี่ยนโค้ดในรอบการวางแผนนี้

## หลักฐานและสาเหตุ

### สิ่งที่เห็นจาก log ใหม่

- งานมี 20 หน้า แต่หน้าแรกใช้เวลารวม 53.37 วินาที และหน้า 2–4 แสดง 91.58–94.26 วินาที
- ตัวเลขต่อหน้าปัจจุบันเริ่มจับเวลาก่อนเข้า `cpu_semaphore` จึงรวมทั้งเวลารอคิวและเวลาประมวลผลจริง ทำให้ยังใช้วิเคราะห์คอขวดแบบละเอียดไม่ได้
- อย่างไรก็ตาม หน้า 4 หน้าแรกทำงานพร้อมกัน และแต่ละหน้าสามารถสร้าง OCR เต็มหน้าความละเอียดสูงหลายชุด จึงแย่ง CPU/RAM กันอย่างหนัก

### สิ่งที่ยืนยันจากโค้ด

- Primary OCR ทำงาน 1 รอบต่อหน้า
- หาก `needs_recovery=True` ระบบจะขยายภาพทั้งหน้าเป็น 2 เท่า แล้วเรียก RapidOCR เพิ่มอีก 2 รอบด้วย shear `-0.12` และ `-0.22`
- ภาพ 2 เท่ามีพิกเซลประมาณ 4 เท่า และ shear ยังขยายความกว้างอีก ดังนั้นหน้าที่เข้า recovery มีภาระรวมประมาณ 9–10 เท่าของ primary pass
- Trigger ใหม่กว้างกว่าเดิม: เพียงมี confidence ต่ำหนึ่งบรรทัด, confidence เฉลี่ยต่ำ หรือพบ dark component ที่ไม่ทับกรอบเดิม ก็ทำให้ทั้งหน้าเข้า recovery
- `_has_uncovered_text_component` คืนเพียง true/false ทั้งที่ตรวจพบตำแหน่ง component แล้ว ทำให้ข้อมูลตำแหน่งหายและระบบต้อง OCR ทั้งหน้าแทนการ crop เฉพาะจุด
- `cpu_semaphore=4` อนุญาตให้ full-page 2× recovery หนัก ๆ ทำพร้อมกัน 4 หน้า ซึ่งอาจช้ากว่าการใช้ concurrency ต่ำกว่าเพราะ memory bandwidth และ ONNX CPU contention

### Benchmark ยืนยันบน fixture ปัจจุบัน

| Fixture | Primary OCR | Pipeline OCR ปัจจุบัน | ช้าลง |
|---|---:|---:|---:|
| `img/1.PNG` | 0.447s | 3.511s | 7.9× |
| `img/2.PNG` | 0.595s | 2.731s | 4.6× |

ผลนี้ยืนยันว่า hot path ใหม่แพง แม้ fixture จะมีขนาดเพียง 722×822 และ 713×533 ซึ่งเล็กกว่าหน้าจริง

## เป้าหมาย

- Stage 1 ของ Chapter 149 จำนวน 20 หน้า มี median ไม่เกิน 45 วินาทีจาก warm run 3 รอบ และ hard ceiling ไม่เกิน 60 วินาที
- หน้าปกติใช้ full-page OCR เพียง 1 inference
- หน้าที่พบข้อความแล้วต้องไม่ทำ full-page 2× shear recovery
- รักษาการพบคำ `VOICE` ใน `img/1.PNG` และ `STONES` ใน `img/2.PNG` ครบ 2/2
- จำนวนข้อความที่ primary OCR พบอยู่แล้วต้องไม่ลดลง
- ไม่สร้าง bubble ซ้ำ, กรอบซ้อน หรือกรอบใหญ่ผิดปกติจาก recovery
- peak CPU/RAM ต้องลดลงอย่างชัดเจนจาก implementation ปัจจุบัน และ UI ต้องไม่ค้างระหว่าง Stage 1

## ลำดับการแก้แบบ TDD

### P0 — เพิ่ม measurement ที่แยกคิวออกจากงานจริง

1. แยกเวลาต่อหน้าเป็น:
   - `queue_wait_ms`: เวลารอ `cpu_semaphore`
   - `process_ms`: เวลาที่ทำ OCR จริงหลังได้ semaphore
   - `base_pass_ms`, `component_scan_ms`, `roi_recovery_ms`
2. บันทึกต่อหน้าโดยไม่เก็บภาพหรือข้อความจริง:
   - trigger reason
   - จำนวน base/ROI/full-page passes
   - จำนวนพิกเซลที่ส่งเข้า OCR แต่ละ pass
   - candidate ที่เพิ่มหรือแทนที่ได้จริง
   - peak in-flight base และ recovery tasks
3. เพิ่ม summary ของ Stage 1: wall time, queue p50/p95, process p50/p95, recovery hit rate และ recovery pixel ratio
4. ทำ benchmark Chapter 149 แบบ warm 3 รอบก่อนแก้ algorithm เพื่อเป็น control เดียวกัน

Tests:

- timer ของหน้าที่รอ semaphore ต้องรายงาน queue wait แยกจาก process time
- log ห้ามมี source dialogue, image bytes, API key หรือข้อมูลลับ
- metric จำนวน pass และ pixel workload ต้องตรงกับ fake OCR calls

### P1 — เปลี่ยนเป็น ROI-first italic recovery

1. เปลี่ยน `_has_uncovered_text_component` ให้เป็นฟังก์ชันค้นหาและคืน immutable candidate boxes พร้อม score แทน boolean
2. รวม dark components ที่อยู่ใกล้กันเป็นกลุ่มข้อความเดียว แล้วเพิ่ม padding และ clamp ให้อยู่ในขอบภาพ
3. ตัด component ที่เป็น panel border, artwork/noise, ใหญ่เกินสัดส่วน หรืออยู่ไกลจากพื้นที่ bubble ที่น่าเชื่อถือ
4. OCR เฉพาะ ROI ที่ primary OCR ยังไม่ครอบ โดยเริ่มจาก:
   - scale 1.5×
   - shear เดียวประมาณ `-0.18`
   - จำกัดไม่เกิน 3 ROIs ต่อหน้า
5. แปลงพิกัดจาก crop + scale + shear กลับสู่พิกัดภาพเดิม แล้ว deduplicate ก่อน grouping
6. ห้ามทำ full-page 2× shear สำหรับหน้าที่ primary OCR พบข้อความแล้ว
7. กรณี primary OCR ไม่พบข้อความเลย ให้คง enhanced full-page fallback เพียง 1 รอบตาม budget เพื่อไม่ให้หน้าเงียบหลุด

Tests:

- component detector ต้องคืนกรอบตำแหน่งและ reject เส้น panel border
- หน้าที่มีข้อความและมี uncovered component ต้องเรียก 1 full-page base pass + bounded crop calls เท่านั้น
- recovery call ต้องมีขนาดเล็กกว่าภาพเต็มหน้า
- crop/shear coordinate mapping ต้องกลับตำแหน่งเดิมถูกต้อง
- no-text page ต้องมี full-page calls รวมไม่เกิน 2 รอบ

### P2 — ทำ trigger ให้เจาะจงและมี budget

1. confidence ต่ำหนึ่งบรรทัดให้กู้เฉพาะ ROI ของบรรทัดนั้น ไม่เปิด recovery ทั้งหน้า
2. uncovered component ให้กู้เฉพาะ component นั้น
3. จำกัดต่อหน้า:
   - `max_recovery_rois=3`
   - recovery pixel budget ไม่เกิน 2× ของจำนวนพิกเซล base image
   - max attempts ต่อ ROI
4. shear รอบที่สองใช้ได้เฉพาะเมื่อรอบแรกไม่เพิ่ม candidate ที่ผ่าน quality score และยังเหลือ pixel budget
5. full-page italic fallback ถ้าจำเป็นจริง ต้องอยู่หลัง feature flag, ใช้ shear เดียว, ไม่ upscale 2× และใช้เฉพาะ no-text page หรือ targeted recovery ที่มีหลักฐานว่ายังขาดข้อความ
6. เก็บเหตุผลที่ข้าม recovery เช่น `budget_exhausted`, `no_valid_component`, `already_covered`

Tests:

- low-confidence line เดียวต้องไม่ทำให้เกิด full-page recovery
- ROI cap, pixel cap และ attempt cap ต้องหยุดงานได้จริง
- second shear ต้องไม่ทำงานเมื่อ first shear สำเร็จ
- budget หมดต้องไม่เกิด retry loop

### P3 — แยก concurrency ตามน้ำหนักงาน

1. แยก semaphore ของ base OCR กับ recovery OCR เพื่อไม่ให้ crop recovery หลายหน้าแย่งทรัพยากรกับ primary pass
2. benchmark concurrency 1/2/3/4 บน Chapter 149 และเลือกค่าที่ wall time ต่ำสุด โดยไม่ดูแค่จำนวนงานพร้อมกัน
3. ค่าเริ่มทดสอบ:
   - base OCR concurrency = 4
   - recovery concurrency = 1–2
4. หาก RapidOCR instance เดียวมี contention/thread-safety ให้ทดสอบ worker-local instance pool เทียบกับ shared instance โดยวัด RAM และ throughput
5. ย้ายค่าเป็น settings เช่น `OCR_BASE_CONCURRENCY`, `OCR_RECOVERY_CONCURRENCY`, `OCR_RECOVERY_MAX_ROIS`, `OCR_RECOVERY_MAX_PIXEL_RATIO`
6. ใช้ weighted/pixel-aware admission เพื่อไม่ให้ภาพใหญ่หลายภาพเข้า recovery พร้อมกัน

Tests:

- max in-flight ต้องไม่เกินค่าที่ตั้ง
- recovery หนักต้องไม่ block base queue ทั้งหมด
- settings ผิดช่วงต้อง fail fast หรือถูก clamp อย่างชัดเจน
- ผลลัพธ์และ reading order ต้อง deterministic ไม่ว่า concurrency เท่าใด

### P4 — รักษาคุณภาพและการรวม bubble

1. เก็บ primary candidate เป็นหลักและแทนที่เมื่อ recovery candidate ชนะด้วย score ที่ดูทั้ง confidence, ตัวอักษร, punctuation และความครบของคำ
2. candidate ใหม่ต้องผ่าน overlap/size/position validation ก่อนเพิ่ม
3. deduplicate ก่อน `_group_lines` เพื่อป้องกันข้อความซ้ำและกรอบทับกัน
4. เก็บ primary line count, recovered line count และ rejected candidate count เพื่อ audit
5. เพิ่ม fixture ระดับหน้าเต็มจาก Chapter 149 หน้า 8 และ 15 เมื่อมีไฟล์ต้นฉบับที่ reproducible; fixture crop ปัจจุบันยังคงเป็น regression ขั้นต่ำ

Tests:

- `img/1.PNG` ต้องยังพบ `VOICE`
- `img/2.PNG` ต้องยังพบ `STONES`
- primary candidate ที่ถูกต้องห้ามถูก candidate confidence สูงแต่ข้อความแย่กว่าเขียนทับ
- ห้ามเกิด duplicate overlap ใหม่หรือกรอบเกินขอบภาพ
- bubble grouping และ reading order ต้องไม่เปลี่ยนแบบ nondeterministic

## Benchmark และเกณฑ์ตัดสิน

รันด้วยภาพและเครื่องเดียวกันอย่างน้อย 3 warm runs แล้วใช้ median:

1. Primary-only control
2. Implementation ปัจจุบันที่ full-page 2× สอง shear
3. ROI-first ที่ recovery concurrency 1
4. ROI-first ที่ recovery concurrency 2
5. ROI-first ที่ base concurrency 2/3/4

ต้องรายงาน:

- Stage 1 wall time
- queue wait และ process p50/p95
- base/ROI/full-page inference count
- OCR pixel workload รวม
- CPU peak, RAM peak
- recovery trigger rate และ useful recovery rate
- จำนวน segments ต่อหน้าและ fixture keyword recall

เลือก configuration ที่เร็วที่สุดเฉพาะเมื่อผ่าน quality gates ทั้งหมด ห้ามเลือกจาก concurrency สูงสุดหรือค่าเฉลี่ยเวลาเพียงอย่างเดียว

## Acceptance Criteria

- Chapter 149 Stage 1 median ≤45s และทุก run ≤60s
- detected-text page มี full-page OCR inference = 1
- recovery pixel workload ต่อหน้า ≤2× base-pixel equivalent
- `VOICE`/`STONES` recall = 2/2
- primary segment retention = 100%
- duplicate/oversized/out-of-bounds boxes ใหม่ = 0
- Stage 1 error หรือหน้าเงียบจาก budget = 0; หากยัง unresolved ต้องมี review flag ชัดเจน
- backend tests ผ่านทั้งหมดและ touched-code coverage ≥80%

## Rollout และ Rollback

1. แยก feature flags สำหรับ ROI recovery, second shear และ recovery concurrency
2. เปิดตามลำดับ: tests → local Chapter 149 replay → canary 10% → 50% → 100%
3. rollback ทันทีหาก Stage 1 p95 แย่กว่า control เกิน 10%, keyword/segment recall ลด, กรอบผิดปกติเพิ่ม หรือ RAM peak เกินเพดาน
4. เก็บ implementation ปัจจุบันเป็น benchmark control เท่านั้น ไม่ใช้เป็น fallback อัตโนมัติใน production เพราะเป็นต้นเหตุของ resource amplification

## Handoff สำหรับโมเดลที่ลงมือแก้

- ทำตาม P0 → P1 → P2 → P3 → P4 แบบ test-first
- ห้ามแก้ด้วยการปิด italic recovery ทั้งหมด
- ห้ามเพิ่ม full-page transform variants เพิ่ม
- ห้ามลดคุณภาพเพื่อให้ตัวเลขเร็วขึ้น; ต้องผ่าน fixture และ segment-retention gates ก่อน
- อัปเดต `CHANGELOG.md`, รัน backend regression/coverage และทำ code review ก่อน commit

---

# แผนเสริมจาก Log ล่าสุด: แยก AI Recovery ออกจาก Stage 3 และเก็บ Log ถาวร

## ข้อจำกัดในการอ่าน Log ปัจจุบัน

- Backend ใช้ `logging.basicConfig` ส่งข้อความไป console เท่านั้น และไม่มี file handler
- หน้าต่าง “Manhwa Backend API” ไม่ได้ผูกกับ terminal session ของ Codex จึงอ่านประวัติย้อนหลังโดยตรงไม่ได้
- รอบนี้วิเคราะห์ได้จากภาพ log ที่แนบและโค้ดปัจจุบัน
- ต้องเพิ่ม rotating log file แบบ structured เพื่อให้ตรวจ job ล่าสุดย้อนหลังได้โดยไม่ต้องอาศัย screenshot

## หลักฐานจาก Job ล่าสุด

- เวลาหลังเริ่ม Stage 1 ถึงจบงานรวมประมาณ **722.86 วินาที (12 นาที 3 วินาที)**:

| Stage | เวลา | สัดส่วนโดยประมาณ | ข้อสรุป |
|---|---:|---:|---|
| Stage 1 OCR | 447.19s | 61.9% | คอขวดใหญ่สุด; เฉลี่ย wall time 22.36s/หน้า |
| Stage 2 primary translation | 150.17s | 20.8% | 4 batches ทำต่อคิวและมี retry/partial recovery ล้ม |
| Stage 3 recovery + render/upload | 125.50s | 17.4% | ประมาณ 111.85s เป็น AI/QC ก่อน render |

- Stage 1 จบใน **447.19 วินาที** เทียบกับ baseline ก่อนเพิ่ม full-page shear ที่ 32.47 วินาที จึงช้าลงประมาณ **13.8 เท่า**
- Page timing ของ Stage 1 เป็นลักษณะ wave/queue: หน้า 1 = 53.37s, หน้า 4 = 91.58s, หน้า 5 = 132.43s และหน้าสุดท้าย = 447.01s ซึ่งสอดคล้องกับงานหนัก 4 หน้าแย่ง CPU/RAM และหน้าถัดไปรอ semaphore
- Stage 2 ใช้ **150.17 วินาที** และได้ 55 translated segments จาก 4 batches:
  - Batch 1 รอบแรกล้ม แล้ว retry สำเร็จรวม 54.59s ได้ 11 segments
  - Batch 2 เก็บ partial ได้ 6 segments แต่ missing-only recovery 22 IDs ล้มหลังรอประมาณ 55.76s
  - Batch 3 สำเร็จ 21.56s ได้ 28 segments
  - Batch 4 สำเร็จ 18.26s ได้ 10 segments
- เวลา Batch 1–4 รวมกันแทบเท่ากับ Stage 2 ทั้งหมด ยืนยันว่า serial contextual batching อยู่บน critical path โดยตรง
- Job `75f70a1c-a55d-4621-8e68-8f2a0e772132` รายงาน Stage 3 รวม **125.50 วินาที** หรือเฉลี่ย 6.27 วินาที/หน้า
- หน้าสุดท้ายรายงาน `processed in 13.65s` โดย Render 4.00s และ Upload 0.44s
- ดังนั้นช่วง render + sequential upload ที่มองเห็นใช้ไม่เกินประมาณ **13.65 วินาที** แต่มีเวลาประมาณ **111.85 วินาที** ก่อน render wave หรือราว **89% ของ Stage 3**
- Page 19 ไม่มี bubble จึง Render 0.00s แต่ยัง Upload 0.41s ยืนยันว่า render ไม่ใช่คอขวดหลักของ 125.50 วินาที
- Upload แต่ละหน้าที่เห็นอยู่ประมาณ 0.40–0.54 วินาที แม้ปัจจุบันทำทีละหน้า จึงมีโอกาสลดเวลาได้อีก แต่ไม่ใช่ต้นเหตุหลัก
- Stage 3 ส่ง page recovery แบบต่อคิวอย่างน้อย 9 หน้า ได้แก่หน้า 3–10 และ 18 รวมอย่างน้อย **41 untranslated segments** จาก log ที่มองเห็น
- งานจบด้วยคำเตือน `some dialogue regions need review` แปลว่าเสียเวลา recovery สูงแล้วยังไม่ปิดช่องว่างคุณภาพทั้งหมด
- มี access log จาก `GET /api/v1/jobs/{job_id}` จำนวนมากตลอดงาน เป็น polling noise ที่บดบัง event สำคัญ; ไม่ใช่คอขวดหลัก แต่ควร sample/filter successful poll logs

## Root Cause จากโค้ด

Stage 3 เริ่มจับเวลาก่อนลูปเตรียม `page_render_jobs` และลูปนี้ยังทำงาน AI/quality แบบต่อคิว:

1. ตรวจ missing/English leakage ต่อหน้า
2. เรียก page-level DeepSeek recovery ทีละหน้า
3. ตรวจ Quality Gate ต่อ segment
4. หากไม่ผ่าน เรียก single-segment QC recovery
5. หากผลยังว่างหรือตรงกับต้นฉบับ เรียก emergency fallback อีกครั้ง
6. หลังจบทุกหน้าแล้วจึงเริ่ม render พร้อมกัน

ผลคือ ID เดียวอาจถูกส่งซ้ำผ่าน page recovery, QC recovery และ emergency fallback และเวลาทั้งหมดถูกนับเป็น Stage 3 ทั้งที่ไม่ใช่งาน render

## P5 — เพิ่ม Persistent Structured Logging

1. เพิ่ม `RotatingFileHandler` ที่เปิด/ปิดและกำหนดตำแหน่งได้ผ่าน settings เช่น `LOG_TO_FILE`, `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`
2. ใช้ไฟล์ JSON Lines หรือ structured key/value ที่ filter ตาม `job_id`, `run_id`, `stage`, `page_index`, `segment_id`, `event` ได้
3. หมุนไฟล์ตามขนาดและเก็บย้อนหลังแบบจำกัด เช่น 10 MB × 5 files เพื่อไม่ให้ disk โตไม่หยุด
4. flush log สำคัญเมื่อ stage/job จบหรือเกิด exception เพื่อให้ crash แล้วข้อมูลยังอยู่
5. ห้ามบันทึก API key, Authorization header, raw image bytes, full prompt, full dialogue หรือ signed URL; log object key/host และ count แทน
6. บันทึก timestamp แบบ timezone ชัดเจนและ duration จาก `perf_counter`
7. เพิ่ม startup event ระบุ logging mode และไฟล์ที่ใช้งานโดยไม่เปิดเผย absolute system path ในข้อความสาธารณะ
8. แยก application pipeline log ออกจาก HTTP access log และ sample/suppress เฉพาะ polling `200 OK` ที่ซ้ำ โดยยังเก็บ non-2xx และ latency ผิดปกติครบ

Tests:

- เปิด file logging แล้วต้องสร้าง/append/rotate ได้
- ปิด setting แล้วต้องไม่เขียนไฟล์
- filter ตาม job ID ต้องได้ lifecycle ครบ Stage 1–4
- secret/header/dialogue redaction tests ต้องผ่าน
- exception ต้องมี type/stack trace แต่ไม่มี payload ลับ
- successful status polling ต้องไม่ flood pipeline log; non-2xx poll ต้องยังค้นพบได้

## P6 — ย้าย Translation/QC Recovery กลับเข้า Stage 2

1. กำหนดขอบเขต stage ใหม่ให้ชัดเจน:
   - Stage 2 = translation, completeness accounting, QC และ provider-local recovery
   - Stage 3 = inpaint, typeset และ upload เท่านั้น
2. หลัง primary translation ให้สร้าง immutable per-segment state map:
   - `PRIMARY_VALID`
   - `MISSING`
   - `QC_FAILED`
   - `RECOVERING`
   - `RESOLVED`
   - `NEEDS_REVIEW`
3. ประเมิน Quality Gate หนึ่งครั้งต่อผลลัพธ์ version และรวม unresolved IDs เป็น recovery queue เดียว
4. ห้ามมี page recovery, QC recovery และ emergency fallback ที่ต่างคนต่างเรียก ID เดียวกัน
5. ใช้ request/attempt budget ต่อ ID; เมื่อครบ budget ให้เป็น `NEEDS_REVIEW` และหยุด retry
6. เก็บ valid partial translations และส่งเฉพาะ missing/invalid IDs ตามแผน DeepSeek เดิม
7. DeepSeek ต้อง retry ด้วย provider/model ที่ผู้ใช้เลือกเท่านั้น ห้ามข้ามไป Groq หรือ DeepSeek model อื่น
8. Groq ใช้ fallback ได้เฉพาะภายใน Groq lane ตาม policy เดิม และห้ามข้ามไป DeepSeek
9. เมื่อ Stage 2 จบ ต้องได้ final result map ที่ immutable; Stage 3 อ่านอย่างเดียวและห้ามเรียก AI client

Tests:

- assert จำนวน AI calls ใน Stage 3 = 0
- ID ที่ primary สำเร็จแล้วต้องไม่ถูก recovery
- ID ที่ขาดต้องเข้าสู่ recovery queue ครั้งเดียวและไม่เกิน attempt budget
- partial response ต้องรักษา valid IDs และ retry เฉพาะ missing IDs
- DeepSeek/Groq provider-model isolation tests ต้องผ่าน
- state transition ผิดลำดับหรือ duplicate completion ต้องถูก reject

## P7 — ทำ Recovery Queue แบบ Bounded และ Context-safe

1. รวม missing/QC-failed segments ตาม page proximity และ token budget แทนการยิงทีละ segment
2. ใช้ bounded waves เพื่อให้ยังส่ง context ของ wave ก่อนหน้าไป wave ถัดไปได้ โดยไม่บังคับทุก request ต่อคิว
3. เริ่ม benchmark recovery concurrency:
   - DeepSeek Flash = 2–3 groups
   - DeepSeek Pro = setting แยกและต่ำกว่า Flash
   - Groq = คง provider-local semaphore เดิม
4. merge ผลตาม segment ID และ reading order แบบ deterministic
5. เก็บ attempt ledger กลางสำหรับ primary/missing-only/QC recovery เพื่อป้องกัน retry ซ้ำคนละ branch
6. แยก issue ที่ซ่อมด้วย deterministic rule ได้ออกจาก AI queue; semantic issues เท่านั้นที่เรียก model
7. บันทึก `recovery_queue_ms`, `api_ms`, `parse_ms`, `qc_ms`, `attempts`, `resolved_count`, `unresolved_count` โดยไม่เก็บ dialogue
8. สำหรับ primary batch ให้เปรียบเทียบสอง policy โดยใช้ context snapshot เดียวกัน:
   - serial control ปัจจุบัน
   - checkpoint waves ขนาด 2 batches สำหรับ Flash และค่าต่ำกว่าสำหรับ Pro
9. หาก batch คืน partial เช่น Batch 2 รอบนี้ที่ valid 6/missing 22 ให้ split เฉพาะ 22 IDs ตาม token budget และทำ bounded recovery groups; ห้ามรอ single missing-only request ก้อนใหญ่ซ้ำจน timeout
10. ตั้ง per-request deadline และ total recovery deadline เพื่อไม่ให้ batch เดียวกิน critical path ประมาณ 55 วินาทีโดยไม่มีผลเพิ่ม

Tests:

- unresolved 10 IDs ต้องทำเป็น bounded groups ไม่ใช่ 10 sequential calls
- max in-flight และ provider semaphore ต้องไม่เกินค่า config
- ordered merge/context snapshot ต้อง deterministic
- attempt ledger ต้องป้องกัน ID เดิมถูกส่งทั้ง page/QC/emergency path
- timeout/429 ต้อง backoff และ terminate ตาม budget
- replay pattern valid 6/missing 22 ต้องรักษา 6, split เฉพาะ 22, และไม่มี request ใดส่ง valid IDs ซ้ำ
- checkpoint wave ต้องลด critical-path wall timeโดยไม่ลด gender/context fixture accuracy

## P8 — Pipeline Render และ Upload โดยรักษาลำดับ Publish

1. เมื่อหน้าหนึ่ง render เสร็จ ให้ upload ได้ทันทีด้วย producer/consumer queue แทนการรอ render ครบทุกหน้า
2. ใช้ semaphore แยก:
   - CPU render/inpaint/typeset
   - R2 upload
3. เริ่ม benchmark upload concurrency 2/4/6 และเลือกค่าที่ p95 ดีโดยไม่สร้าง network saturation
4. เก็บ `staged_pages` แบบ immutable แล้ว sort ด้วย page index ก่อน atomic publish
5. หน้าไม่มี approved bubble ให้ข้าม inpaint/typeset และส่ง raw bytes เข้า upload ตามเดิม
6. coalesce progress DB updates เพื่อไม่ให้การอัปเดตทีละหน้ากลายเป็นคอขวด
7. log แยก `render_queue_ms`, `render_ms`, `upload_queue_ms`, `upload_ms` และ end-to-end page latency

Tests:

- upload ต้องเริ่มได้ก่อน render ทุกหน้าจบ
- completion order สลับกันได้ แต่ publish order ต้อง 1..N เสมอ
- cancellation ก่อน publish ต้องไม่เผย staged chapter บางส่วน
- upload failure ต้อง retry แบบ bounded และไม่เขียน page ซ้ำ
- no-bubble page ต้องไม่เรียก inpaint/typeset

## P9 — แก้ Metric ที่ทำให้ตีความผิด

1. แยก Stage 3 เป็น summary ย่อย:
   - `3A result assembly` ซึ่งควรไม่มี AI calls
   - `3B render`
   - `3C upload`
   - `3D publish staging`
2. เวลา `Page processed` ต้องรายงานทั้ง queue wait และ active duration ไม่ใช้ timestamp ที่เริ่มก่อนงานรอคิวเป็น compute time
3. Stage wall time ใช้เวลาจริงของ critical path; ห้ามใช้ผลรวม per-page durations เป็น wall time
4. log จำนวน AI calls แยกตาม primary/recovery และ stage เพื่อจับ regression ที่ AI หลุดกลับเข้า Stage 3
5. เพิ่ม final job summary ที่รวม Stage 1, Stage 2 primary, Stage 2 recovery, Stage 3 render, Stage 3 upload และ DB/publish

## Acceptance Criteria เพิ่มเติม

- Stage 3 ต้องมี AI calls = 0
- Stage 3 ของ Chapter 149 จำนวน 20 หน้า median ≤18 วินาที และ hard ceiling ≤25 วินาทีจาก warm run 3 รอบ
- เวลาที่เคยซ่อนก่อน render ประมาณ 111.85 วินาทีต้องย้ายไป metric Stage 2 recovery และลดลงด้วย bounded queue
- duplicate recovery request ต่อ segment = 0
- unresolved ทุก ID ต้องเป็น `NEEDS_REVIEW` พร้อม issue code; ห้ามเงียบหรือ publish source text เป็นคำแปล
- render/upload output, page count และ page order ต้องเหมือน baseline
- rotating log ต้องค้น job ล่าสุดย้อนหลังได้และไม่มี secret/dialogue leakage
- เมื่อทำร่วมกับแผน Stage 1 ให้รายงาน critical path ทั้งตอนใหม่; ห้ามอ้างว่าเร็วขึ้นจากการย้ายชื่อ stage เพียงอย่างเดียว
- Stage 1 ต้องลดจาก baseline ล่าสุด 447.19s ตามเกณฑ์ Stage 1 เดิม โดยคง fixture recall
- Stage 2 primary + bounded recovery median ≤75s และ request เดี่ยวต้องไม่ครอง critical pathเกิน configured deadline
- end-to-end เป้าหมายรอบแรก ≤145s สำหรับ 20 หน้า และ stretch target ≤110s หลัง context checkpoint waves ผ่าน quality gates
- polling access-log volume ต้องลดลงอย่างน้อย 90% โดย error visibility ไม่ลดลง

## ลำดับทำร่วมกับแผน Stage 1

1. ทำ P0 Stage 1 metrics และ P5 persistent logging ก่อน เพื่อเก็บ baseline ที่เชื่อถือได้
2. ทำ P1–P2 ROI-first OCR และ budget
3. ทำ P6 ย้าย recovery ไป Stage 2 พร้อม attempt ledger
4. ทำ P7 bounded recovery queue
5. ทำ P3 OCR concurrency และ P8 render/upload pipeline
6. ทำ P4/P9 quality + metric verification
7. replay Chapter 149 อย่างน้อย 3 warm runs แล้วเปรียบเทียบ Stage 1, Stage 2 recovery, Stage 3 และเวลารวมทั้งตอน

---

# แผนเสริมด้านคุณภาพ: Source OCR ถูกต้องและหนึ่ง Bubble แปล/วาดเพียงครั้งเดียว

## Capability

ระบบต้องสร้าง source transcript ที่ตรวจสอบได้จากแต่ละ speech bubble ก่อนส่ง AI และต้องมี translation/render instruction เพียงหนึ่งรายการต่อ visual bubble แม้ OCR จะทดลองหลาย transform หรือมี recovery หลายรอบ

## หลักฐานจาก Fixture จริง

ผล OCR ปัจจุบันจากไฟล์ใน `img/` ยังผิดดังนี้:

| Fixture | OCR ปัจจุบัน | Source ที่ต้องได้ |
|---|---|---|
| `img/1.PNG` bubble 1 | `LO SHU'S VOICE!!` | `LU SHU'S VOICE!!` |
| `img/1.PNG` bubble 2 | `OHS 01 PLEASE HELP ME TRANSLAT....` | `LU SHU, PLEASE HELP ME TRANSLATE...` |
| `img/1.PNG` bubble 3 | `EH, WHERE 15 HE?` | `EH, WHERE IS HE?` |
| `img/2.PNG` | `DON'T! IS THIRTY-FINE OKAY? ...` | `DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!` |

ดังนั้นปัญหาไม่ได้อยู่ที่โมเดลแปลอย่างเดียว เพราะ source ที่ส่งเข้าโมเดลมี `LO`, `OHS 01`, `15` และ `THIRTY-FINE` ตั้งแต่ต้น

ผลภาพซ้ำ/ทับกันเกิดได้จาก contract ปัจจุบัน:

- OCR transform หลายชุดสามารถเพิ่ม candidate ที่ข้อความต่างกันเล็กน้อยเป็นคนละ line/segment เพราะ duplicate check ใช้ same-text หรือ IoU สูงเป็นหลัก
- `_group_lines` เดาความเป็น bubble จากระยะ/ตำแหน่ง โดยไม่มี bubble identity หรือ contour ที่คงที่
- recovery result สามารถกลายเป็นรายการเพิ่ม แทนที่จะ replace candidate ของ visual region เดิม
- typesetter รับเพียง `{box, text}` แล้ววาดทุกรายการตามลำดับ โดยไม่มี `region_id`, uniqueness validation หรือ collision preflight
- inpainter ล้างตามกล่อง OCR แต่ถ้ากล่องไม่ครอบทุกบรรทัด อักษรอังกฤษเดิม เช่น `STONES?` สามารถเหลืออยู่ใต้/ข้างคำแปล

## User-visible Translation Contract

Fixture ต้องได้ความหมายอย่างน้อยดังนี้ โดยชื่อใช้รูปมาตรฐานจาก glossary เดียวกันทั้งตอน:

### `img/1.PNG`

1. `เสียงของลูซู!!`
2. `ลูซู ช่วยฉันแปลหน่อย...`
3. `เอ๊ะ เขาอยู่ไหน?`

### `img/2.PNG`

- `ไม่! 35 โอเคไหม? เอาทั้งหมดเลยด้วยราคา 35 หินวิญญาณ!`
- อนุญาตใช้เลข `35` แทนคำว่า `สามสิบห้า` แต่ค่าต้องปรากฏครบสองตำแหน่งและความหมายห้ามเปลี่ยน

ข้อความข้างต้นเป็น semantic acceptance target ไม่ใช่การ hardcode คำแปลเข้า production code

## Invariants ที่ห้ามละเมิด

1. หนึ่ง visual bubble region มี selected source transcript ได้หนึ่งชุด
2. OCR transforms/recovery สร้าง candidate evidence เท่านั้น ห้ามสร้าง translation unit ใหม่โดยตรง
3. หนึ่ง `region_id` มี `OCRSegment` ที่ active ได้ไม่เกินหนึ่งรายการ
4. หนึ่ง `region_id` มี final translation และ render instruction ได้ไม่เกินหนึ่งรายการ
5. recovery ต้อง replace state ของ region เดิมแบบ immutable ห้าม append สำเนา
6. bubble คนละ contour ต้องไม่ถูก merge แม้ข้อความเหมือนกันหรืออยู่ใกล้กัน เช่นคำทักทายในภาพ 3
7. source ที่ยังมี OCR corruption ต้องเป็น `SOURCE_NEEDS_REVIEW` และห้ามส่งแปล/เผยแพร่แบบเงียบ
8. inpaint coverage ต้องครอบ source glyphs ทั้งหมดของ region แต่ห้ามออกนอก safe bubble mask ไปทับภาพวาด
9. Stage 3 ต้องปฏิเสธ duplicate/colliding render instructions ก่อนแก้ภาพ

## P10 — เพิ่ม Bubble Region และ Candidate Contract

1. เพิ่ม immutable contract แยกชัดเจน:
   - `BubbleRegion`: `region_id`, page, contour/mask, safe interior, reading order
   - `OCRCandidate`: region, transform, polygon/box, raw text, confidence, component coverage
   - `SelectedSource`: region, normalized transcript, selected evidence, source status, issue codes
   - `RenderInstruction`: region, clean mask/union box, safe text box, final Thai
2. สร้าง `region_id` แบบ deterministic จาก page + contour/quantized geometry เพื่อให้ primary/recovery อ้าง region เดิมได้
3. map OCR lines จากทุก transform เข้า bubble region ก่อนทำ candidate selection
4. `segment_id` อ้าง region identity ไม่ใช่ลำดับชั่วคราวที่เปลี่ยนเมื่อ candidate เพิ่ม/หาย
5. รักษา backward compatibility ที่ boundary ชั่วคราว แต่ห้ามแปลงข้อมูลแล้วทำ region identity หาย

Tests:

- region ID ต้อง deterministic เมื่อ transform/polygon ขยับเล็กน้อย
- candidates หลาย transform ใน contour เดียวต้องอยู่ region เดียว
- bubble contour คนละอันที่อยู่ชิดกันต้องได้คนละ region
- request contract ต้อง reject duplicate active `region_id`

## P11 — Source OCR Quality Gate ก่อน Translation

1. สร้าง `SourceQualityGate` แยกจาก Translation Quality Gate เพื่อตรวจ:
   - token ผสมตัวเลข/ตัวอักษรผิดธรรมชาติ เช่น `O1`, `15 HE`
   - truncated word เช่น `TRANSLAT....`
   - transform disagreement สูง
   - coverage ยังเหลือ dark text components
   - repeated phrase ขัดกัน เช่น `THIRTY-FINE` กับ `THIRTY-FIVE`
   - proper noun ต่างจาก locked glossary/entity ใกล้เคียงอย่างมีนัยสำคัญ
2. source ที่ fail gate เข้า targeted ROI re-recognition ตาม pixel budget ไม่ส่งเข้า AI แปลทันที
3. ทำ line-crop recognition ensemble แบบ bounded: original, contrast/CLAHE และ shear ที่มีหลักฐาน โดยใช้แผน ROI-first เดิม
4. เลือก candidate ด้วยคะแนนรวม:
   - confidence
   - visual component coverage
   - agreement ระหว่าง transforms
   - punctuation/clause completeness
   - English token plausibility
   - glossary/entity support
5. lexical/glossary correction ใช้ได้เฉพาะเมื่อ edit/confusion path สั้นและมี visual candidate สนับสนุน ห้ามเดาคำใหม่จากภาษาอย่างเดียว
6. รองรับ confusion แบบทั่วไป เช่น `I/1`, `S/5`, `O/0`, `V/F`, `U/O` โดยเก็บ raw evidence ไว้ audit
7. repeated term ภายใน bubble/chapter ต้องใช้ canonical form เดียวกันเมื่อ visual evidence สนับสนุน เช่น `THIRTY-FIVE` สองตำแหน่ง
8. หากยังตัดสินไม่ได้ ให้ `SOURCE_NEEDS_REVIEW` พร้อม crop/evidence reference แบบ local/debug เท่านั้น

Tests:

- `img/1.PNG` ต้องได้ source exact ทั้งสาม clauses ตามตาราง
- `img/2.PNG` ต้องได้ `THIRTY-FIVE` สองครั้งและ `STONES!`
- ห้ามมี `LO SHU`, `OHS 01`, `15 HE`, `THIRTY-FINE` ใน selected source
- confidence สูงแต่ token ผิดต้องไม่ผ่าน Source Quality Gate
- เลข `35` ที่เป็นตัวเลขจริงต้องไม่ถูกแก้เป็น `IS`; confusion correction ต้องอาศัยตำแหน่งและ visual consensus
- proper noun ที่ไม่อยู่ glossary ต้องไม่ถูก autocorrect หากไม่มี candidate consensus สนับสนุน
- glossary ต้องไม่เปลี่ยนคำที่ edit distance/visual evidence ไม่รองรับ
- unresolved source ต้องไม่ถูกส่งเข้า translator

## P12 — Candidate Consensus และ Bubble-level Grouping

1. เลิก append shear/enhanced detections ตรงเข้าสู่ `lines`; เก็บเป็น candidates ของ region
2. ทำ spatial association ด้วย bubble contour membership ก่อน แล้วใช้ overlap/containment/center distance ภายใน region
3. รวม multi-line transcript ตาม baseline/reading order ภายใน bubble maskเดียวกัน
4. ใช้ character/word consensus ระหว่าง variants เพื่อแก้หนึ่งตัวอักษรโดยไม่เพิ่ม segment ใหม่
5. candidate ที่ครอบบางบรรทัดต้องไม่แยกเป็น bubble ใหม่ หากอยู่ contour เดียวกับ candidate ที่ครบกว่า
6. NMS/duplicate collapse ต้องดูทั้ง containment, normalized edit similarity และ shared region ไม่พึ่ง IoU 0.7 อย่างเดียว
7. ห้าม merge ข้าม region แม้ normalized text เหมือนกัน เพื่อรักษา bubble ทักทายสองช่องในภาพ 3

Tests:

- base `THIRTY-FINE` + recovered `THIRTY-FIVE` ต้องเหลือ selected region หนึ่งรายการ
- full transcript + partial transcript ใน bubble เดียวต้องเหลือ translation unit เดียว
- candidate boxes ซ้อนกันแต่คนละ bubble contour ต้องคงสอง regions
- reading order ต้องคงที่เมื่อ candidate input สลับลำดับ

## P13 — Translation Fidelity Gate สำหรับ Source ที่ตรวจแล้ว

1. ส่ง translator เฉพาะ `SOURCE_VERIFIED` หรือ `SOURCE_RECOVERED`
2. แนบ locked entity glossary เพื่อให้ `LU SHU` ใช้ `ลูซู` สม่ำเสมอทั้งตอน
3. เพิ่ม semantic checks:
   - proper noun coverage
   - question/negation preservation
   - clause count/completeness
   - repeated numeric value preservation รวมเลขไทย/คำอ่านไทย
   - no English/OCR garbage leakage
4. สำหรับ `img/2.PNG` ต้องตรวจว่า 35/สามสิบห้าปรากฏสองครั้ง ไม่ใช่ตรวจแค่ชุดตัวเลข ASCII ปัจจุบัน
5. translation repair ห้ามแก้ selected source; หากพบว่า source ผิดต้องย้อนกลับ Source OCR recovery state อย่างชัดเจน
6. เก็บ source issue กับ translation issue คนละ namespace เพื่อไม่ให้ AI translation ถูกใช้ปกปิด OCR corruption

Tests:

- semantic targets ของ `img/1.PNG` ครบสามข้อความ
- `img/2.PNG` ต้องรักษา negation และจำนวน 35 ทั้งสองตำแหน่ง
- `ลูซู` ต้องตรง glossary ทุก bubble
- output ที่ยังมี `O1`, `15`, `THIRTY-FINE` หรือ source English ต้องไม่ผ่าน

## P14 — One Bubble, One Render Instruction

1. เปลี่ยน `approved` จาก list ของ `{box, text}` เป็น immutable map keyed by `region_id`
2. recovery update ต้อง replace value ใน map เดิม และ attempt ledger ต้องป้องกันผลซ้ำ
3. ก่อน inpaint/typeset ทำ render preflight:
   - unique region IDs
   - box/mask อยู่ในภาพ
   - no duplicate instruction
   - no unsafe collision
   - final text ผ่าน QC
4. หาก instruction สองรายการอ้าง region เดียว ให้ reject upstream bug ห้ามวาดทั้งคู่
5. หาก instruction คนละ region แต่ text boxes ชนกัน ให้ fit/reflow ใน safe interior หรือ `NEEDS_REVIEW`; ห้ามวาดทับ
6. typesetter ต้องรับ region identity และวาดหนึ่งครั้งต่อ region
7. ทำ idempotency test: เรียก render ด้วย final state เดิมซ้ำต้องไม่ทำให้มีข้อความเพิ่ม

Tests:

- duplicate `region_id` ต้องถูก reject ก่อนแก้ภาพ
- primary + recovery result ของ region เดียวต้องวาดเพียงครั้งเดียว
- two distinct greeting bubbles ต้องวาดแยกคนละหนึ่งครั้ง
- collision preflight ต้องจับภาพลักษณะเดียวกับภาพ 4

## P15 — Inpaint Coverage โดยไม่ลบภาพวาด

1. สร้าง clean mask จาก union ของ glyph/text components ที่ยืนยันแล้วภายใน bubble region ไม่ใช้กล่อง translation แต่ละ candidate แยกกัน
2. เพิ่ม padding ตามขนาดตัวอักษรและ anti-aliasing แต่ clamp ภายใน safe bubble mask
3. ตรวจ residual dark text components หลัง inpaint ก่อน typeset
4. ถ้ายังเหลือ source text เช่น `STONES?` ให้ทำ bounded mask expansion/re-inpaint ก่อนวาดคำแปล
5. ห้ามขยายเป็น rectangle ใหญ่ทั้ง bubble/page โดยไม่มี mask เพราะเคยเกิดการลบภาพและกรอบใหญ่
6. วาง Thai text ใน safe interior ของ bubble ไม่ใช้ union glyph box ที่แคบหรือเยื้องเป็น layout box โดยตรง

Tests:

- visual fixture ต้องไม่มี original English glyphs เหลือใน cleaned region
- pixel ภายนอก bubble safe mask ต้องไม่เปลี่ยนเกิน tolerance
- clean mask ต้องครอบทุก source line แต่ไม่รวม bubble outline/tail/artwork
- หลัง typeset ต้องมี Thai text block เดียวต่อ region

## P16 — Golden Fixtures และ Visual Regression

1. ใช้ `img/1.PNG` และ `img/2.PNG` เป็น golden source fixtures แบบ exact transcript ไม่ใช่เพียงเช็คว่ามีคำ `VOICE`/`STONES`
2. เก็บ expected region count, line order, selected source, union clean mask bounds และ semantic Thai assertions
3. เพิ่มต้นฉบับของกรณีภาพ 3–4 เป็น fixtures ก่อน implementation; screenshot ผลลัพธ์อย่างเดียวไม่พอสำหรับ pixel-level test
4. ทำ synthetic fixtures เพิ่ม:
   - same bubble, two OCR candidates
   - two adjacent bubbles, same text
   - partial line + full line
   - original English residual after undersized box
5. สร้าง visual diff artifacts เฉพาะ test/debug และไม่เก็บ dialogue/image production ลง persistent logs

## Acceptance Criteria ด้านคุณภาพ

- `img/1.PNG`: region count = 3 และ selected source ตรงครบทั้งสาม clauses
- `img/2.PNG`: region count = 1, `THIRTY-FIVE` = 2 ครั้ง, `STONES!` = 1 ครั้ง
- semantic Thai ตรงตาม User-visible Translation Contract
- selected source corruption tokens = 0
- duplicate active regions/translation/render instructions = 0
- translated text blocks ต่อ region = 1
- residual English glyphs ใน cleaned region = 0 ตาม component/pixel threshold
- artwork pixels นอก safe mask เปลี่ยนไม่เกิน tolerance
- adjacent distinct bubbles ไม่ถูก merge
- unresolved source/translation ถูก flag และไม่ publish แบบเงียบ
- quality logic เพิ่มเวลา clean page ไม่เกิน 100ms และ recovery ยังอยู่ภายใต้ ROI pixel budget จากแผน Stage 1

## ลำดับทำร่วมกับแผนเดิม

1. เพิ่ม exact golden fixture contracts ใน P16 ก่อนแก้ OCR
2. ทำ P10 region/candidate contracts และ P11 Source Quality Gate
3. ทำ P1/P2 ROI-first recovery ร่วมกับ P12 candidate consensus
4. ทำ P13 translation fidelity และเชื่อมกับ Stage 2 recovery state machine P6/P7
5. ทำ P14 render uniqueness และ P15 mask coverage
6. ทำ Stage 1/2/3 benchmark และ visual regression พร้อมกัน
7. code review ต้องตรวจทั้ง correctness, performance, provider isolation และ pixel safety ก่อน rollout

## Non-goals

- ไม่ hardcode ประโยค Chapter 149 ลง production
- ไม่ใช้ AI translation เดาแก้ OCR source โดยไม่มี visual evidence
- ไม่ merge bubble เพียงเพราะข้อความเหมือนกัน
- ไม่เพิ่ม full-page OCR variants จน performance ถอยอีก
- ไม่ยอมให้ typesetter วาดต่อเมื่อ preflight พบ duplicate/collision
