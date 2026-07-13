# แผนกู้คืนระบบแปลให้ครบ เร็ว คุณภาพดี และคุมค่า API

## สถานะและขอบเขต

เอกสารนี้เป็นแผนสำหรับ model ที่จะลงมือแก้ในรอบถัดไป ยังไม่อนุญาตให้เปลี่ยนโค้ดจากขั้นตอนวางแผนนี้

เป้าหมายคือให้ทุก `region_id` ที่ระบบกรอบเดิมตรวจพบมีคำแปลไทยที่ผ่าน QC ก่อนเผยแพร่ โดยไม่ทิ้งภาษาอังกฤษ ไม่ปล่อยช่องว่าง ไม่วาดคำแปลซ้ำ ใช้ context ให้บทพูดเป็นธรรมชาติเหมือนคนแปล และทำงานภายในเวลา/ค่า API ที่ควบคุมได้

## ข้อห้ามและ invariant ที่ต้องรักษา

- ห้ามเปลี่ยน bubble detection, grouping, contour, bounding box, mask, reading order หรือขนาดกรอบ
- ห้ามรวม แยก ลบ หรือสร้าง region ด้วย geometry, IoU หรือการซ้อนของกรอบเพื่อแก้ปัญหาคำแปลซ้ำ
- ปัญหาคำแปลซ้ำต้องแก้ด้วย `region_id` และ translation state เท่านั้น
- OCR recovery สำหรับอักษรเอียง/อ่านยาก อ่านใหม่ได้เฉพาะภายในกรอบและ `region_id` เดิม แล้วเปลี่ยนเฉพาะ `source_text`; ห้ามแก้พิกัดหรือเพิ่ม region
- DeepSeek ต้องใช้ provider และ model ที่ผู้ใช้เลือกตลอดทั้ง primary/recovery ห้ามข้ามไป Groq หรือ DeepSeek model อื่น
- Groq สลับ model ได้เฉพาะ model ภายใน Groq และห้ามข้ามไป DeepSeek
- Stage 3 มีหน้าที่ inpaint, typeset และ upload เท่านั้น ห้ามเรียก AI
- ผลที่ `APPROVED` แล้วห้ามถูกส่งไปแปลซ้ำหรือถูกผลที่แย่กว่าเขียนทับ

## หลักฐานจากงานที่ล้มล่าสุด

อ้างอิง job `a1853287-df72-4368-aaaf-4e910d98e1d2`:

- Chapter 149 มี 20 หน้า และ 89 translation regions
- Stage 2 ได้คำแปลที่ parser รับได้แล้ว 76 regions
- ก่อนเข้า final QC ยังเหลือ 13 pending regions; Stage 3 ระบุ 12 IDs ที่ว่าง/ยังเป็น source อย่างชัดเจน (`9:1`, `9:2`, `10:1`–`10:5`, `14:2`–`14:4`, `15:8`, `15:9`) ส่วนอีกหนึ่งรายการต้องแยกจาก artifact ว่าเป็น quality rejection ใด ห้ามสรุปรวมแบบเดา
- ระบบเพิ่ม `ocr-unverified:<page>` อีก 20 รายการเข้า list เดียวกัน จึงแสดง `33 dialogue regions remain unresolved` ทั้งที่ 20 รายการนั้นเป็น page-level diagnostic ไม่ใช่ช่องคำพูด
- OCR log ระบุ `coverage_verified=false` เกือบทุกหน้า เพราะ component heuristic พบ dark component หรือ recovery semaphore เต็ม แม้ primary OCR จะคืน regions ได้แล้ว
- Batch 2 ได้ 17 translations และขาด 7 IDs; Batch 3 ได้ 10 translations และขาด 18 IDs
- DeepSeek ตอบ HTTP 200 หลายครั้ง แต่ parser ไม่พบ translation ที่รับได้แล้วโยน generic `RuntimeError("DeepSeek batch result is incomplete")`
- recovery ส่ง request ต่อหลัง contract failure โดยไม่มีข้อมูลชัดว่า response ว่าง, JSON เสีย, truncated, ID ผิด หรือ output token ไม่พอ
- Stage 2 ใช้ 141.95 วินาที แต่ยังจบด้วย 13 missing translations
- UI แสดง `approval_retry_budget_exhausted` แม้ log ไม่ได้พิสูจน์ว่า dollar budget หมดจริง
- process runner log ว่า job “completed successfully” แม้ job status เป็น `FAILED`

## สาเหตุหลักที่ต้องแก้

1. Page-level OCR warning ถูกนับรวมกับ translation failure ทำให้หน้าที่เคยแปลได้ถูก block ทั้งบท
2. DeepSeek HTTP 200 contract failures ถูกยุบเป็น `RuntimeError` เดียว จึงเลือก recovery strategy ไม่ถูก
3. fixed recovery output 800 tokens และกลุ่ม recovery ที่ใหญ่สามารถทำให้ JSON ขาดหรือไม่มีรายการที่ parser ยอมรับ
4. retry ทำซ้ำโดยไม่ adaptive split และไม่ส่ง draft/issue codes ไปให้โมเดลซ่อมเฉพาะจุด
5. quality gate ยังไม่มี severity ที่แยก hard correctness failure ออกจาก soft semantic/style review
6. state ของ translation กระจายหลาย branch ทำให้การนับ attempt, missing IDs, approved IDs และสาเหตุสุดท้ายคลุมเครือ
7. สถานะ backend, runner log และ UI ไม่ใช้ failure taxonomy เดียวกัน

## P0 — หยุด regression และคืนความหมายของสถานะให้ถูกต้อง

1. สร้าง snapshot regression จาก baseline กรอบเดิมสำหรับ Chapter 149 และ fixtures ใน `img/`:
   - `region_id`
   - จำนวน regions ต่อหน้า
   - box coordinates
   - reading order
2. ทุก test และ implementation ในแผนนี้ต้องผ่าน snapshot แบบ exact; หากกรอบเปลี่ยนให้ถือว่า regression และหยุดงาน
3. แยกสถานะออกเป็นคนละชุด ห้ามนับรวม:
   - `missing_translation_ids`
   - `quality_rejected_ids`
   - `ocr_source_review_region_ids`
   - `ocr_diagnostic_pages`
   - `response_contract_errors`
4. `coverage_verified=false` จาก heuristic ต้องเป็น diagnostic จนกว่าจะมีหลักฐานตำแหน่งข้อความที่ตกหล่นจริง:
   - ห้ามแปลง page warning เป็น dialogue ID
   - ห้ามใช้ warning นี้แก้/ลบ/รวมกรอบ
   - hard block ได้เฉพาะเมื่อ audit ระบุ region หรือ crop ที่มี source text ตกหล่นจริง
5. แก้ runner ให้ log และคืนผลตาม terminal status จริง: `COMPLETED`, `FAILED`, `PAUSED_COST_LIMIT`, `CANCELLED`
6. UI ต้องแสดงสาเหตุจริง ห้ามแนะนำว่าเข้าถึงเว็บต้นฉบับไม่ได้เมื่อปัญหาอยู่ที่ translation/QC

## P1 — เปลี่ยน generic RuntimeError เป็นผลลัพธ์ที่กู้คืนได้

สร้าง structured batch outcome ที่คืน valid partial results เสมอ:

- `COMPLETE`
- `PARTIAL`
- `EMPTY_CONTENT`
- `INVALID_JSON`
- `TRUNCATED_JSON`
- `MISSING_IDS`
- `DUPLICATE_IDS`
- `UNKNOWN_IDS`
- `TRANSPORT_RETRYABLE`
- `TRANSPORT_PERMANENT`

ข้อกำหนด:

1. HTTP 200 ที่ response contract ผิดห้ามโยน generic `RuntimeError` และทำข้อมูลสาเหตุหาย
2. parser ต้องเก็บทุก valid expected ID แม้ JSON ส่วนท้ายขาด
3. บันทึกเฉพาะ metadata ที่ปลอดภัย: outcome, response byte count, finish reason, expected/parsed/missing counts, token usage และ latency; ห้าม log dialogue/API key/raw response
4. ใช้ response schema เดียวทุก call คือ `segment_id` และ `translation`; alias เก่ารองรับเฉพาะที่ประกาศชัดเจน
5. 429/5xx/timeout ใช้ bounded backoff และ `Retry-After`
6. HTTP 200 contract failure ห้ามส่ง payload เดิมซ้ำแบบ blind retry; ต้อง adaptive split ทันที
7. 401/403/invalid request หยุดทันทีด้วยสาเหตุถาวร ไม่เสีย retry budget

## P2 — สร้าง translation ledger หนึ่ง state ต่อหนึ่ง region

ใช้ immutable map keyed by `region_id` โดยมีข้อมูลอย่างน้อย:

- `segment_id`
- `source_text` และ source verification state
- `active_translation`
- `state`: `PENDING | DRAFT | REPAIR_PENDING | APPROVED | PAUSED | FAILED`
- `issue_codes` แยก hard/soft
- `attempt_count`
- `request_fingerprints`
- `provider` และ `model`
- input/output tokens, cost และ latency

กติกา:

1. หนึ่ง region มี active translation ได้เพียงหนึ่งค่า
2. recovery ต้อง replace candidate ใน state เดิม ห้าม append translation/render item
3. response ที่มี ID ซ้ำ apply ได้ครั้งเดียว และต้องไม่สร้าง overlay ซ้ำ
4. region ที่ approved แล้วไม่เข้า retry queue อีก
5. candidate ใหม่แทน candidate เดิมได้เมื่อผ่าน QC หรือมี hard issue น้อยลงโดยไม่ทำ correctness ที่เคยผ่านให้เสีย
6. render instruction สร้างจาก approved ledger หนึ่งรายการต่อ `region_id`
7. ห้ามใช้ตำแหน่งหรือ overlap ของกรอบเป็นตัวตัดสิน duplicate translation
8. checkpoint ledger หลัง primary batch และ recovery wave เพื่อ resume เฉพาะ unresolved IDs ได้

## P3 — Quality Gate ที่รักษาคุณภาพโดยไม่ปัดคำแปลดีทิ้ง

### Hard blockers

- ค่าว่างหรือเหมือน source
- English leakage ที่ไม่อยู่ allowlist ชื่อเฉพาะ/ศัพท์ระบบ
- meta text หรือคำอธิบายจากโมเดล
- missing/duplicate/unknown segment ID
- clause สำคัญหรือคำปฏิเสธหาย
- ตัวเลข จำนวน ระดับพลัง หรือหน่วยผิด หลัง normalize เลขอารบิก เลขไทย และคำอ่านเลข
- locked glossary ผิด
- เพศ/สรรพนามผิดเมื่อ character evidence ยืนยันได้
- JSON/response contract ใช้งานไม่ได้

### Soft review

- length ratio โดยไม่มีหลักฐานว่าความหมายหาย
- ประโยคยาว
- stylistic preference
- คำกำกวม
- semantic-risk keyword เพียงอย่างเดียว

กติกา:

1. soft issue ห้ามทำให้งานล้มทันที
2. ส่ง semantic repair เฉพาะ region ที่มี soft issue โดยแนบ source, draft, issue, glossary, character/gender context และบทก่อนหน้า/ถัดไป
3. repair prompt ต้องสั่ง “แก้ draft” ไม่ใช่เริ่มแปลใหม่โดยไม่รู้ข้อผิดพลาด
4. คำแปลสุดท้ายต้องรักษาทุก clause, negation, number, rank, name และ relationship
5. ภาษาไทยต้องเป็นธรรมชาติ กระชับตามพื้นที่ bubble และคงน้ำเสียงตัวละคร
6. สร้าง issue histogram จาก Chapter 149 เพื่อปรับ threshold ด้วยข้อมูลจริงก่อนเปิด hard gate ใหม่

## P4 — Adaptive DeepSeek recovery ที่ครบและไม่เกิด retry storm

1. Primary batch คง reading order และ context ต่อเนื่อง สูงสุด 5 หน้า แต่ต้องมี segment/output-token budget เพิ่มเติม
2. benchmark primary segment caps `16`, `24`, `32` เทียบกับค่าปัจจุบัน; เลือกค่าที่ completeness สูงสุดก่อน latency
3. recovery split ตามลำดับ `8 → 4 → 2 → 1` เมื่อเกิด empty/invalid/truncated/missing contract outcome
4. คำนวณ `max_output_tokens` ตามจำนวน segment และความยาว source แทน fixed 800 โดยมี hard cap ต่อ request
5. payload fingerprint เดิมส่งซ้ำได้ไม่เกิน 2 ครั้ง และใช้ซ้ำเฉพาะ transport failure
6. valid partial translations ต้อง commit ทันที แล้ว retry เฉพาะ IDs ที่เหลือ
7. recovery คนละ chunk ทำพร้อมกันแบบ bounded concurrency; เริ่ม benchmark Flash ที่ concurrency 2 และ 3
8. หลัง contract fail ห้าม sleep แบบ backoff; split แล้วทำต่อทันที ส่วน backoff ใช้เฉพาะ network/429/5xx
9. single-ID recovery ใช้ prompt/response สั้น พร้อม context เท่าที่จำเป็น
10. Stage 2 ต้องจบด้วย ledger ที่ทุก region เป็น `APPROVED` หรือ terminal reason ที่เจาะจง; Stage 3 ห้ามกู้คำแปล
11. DeepSeek ทุก call ตรวจ assertion ว่า provider/model ตรงกับ job เดิม
12. Groq recovery แยก implementation/config และสลับได้เฉพาะ Groq models

## P5 — Source OCR ยากโดยไม่แตะกรอบ

1. ใช้ region/box pipeline เดิมเป็น expected set
2. หาก source quality สงสัย ให้ crop ภายใน box เดิมและทำ OCR candidate ensemble แบบ bounded
3. recovery เปลี่ยนเฉพาะ source candidate ของ region เดิม; region ID, box และ reading order ต้องคงเดิม
4. เลือก source ด้วย visual consensus, confidence, punctuation/clause completeness และ glossary evidence
5. กรณีอักษรเอียงต้องมี fixtures exact transcript สำหรับ `VOICE`, `LU SHU`, `IS HE`, `THIRTY-FIVE` สองตำแหน่ง และ `STONES`
6. หากยังอ่าน source ไม่ได้ ให้สถานะ `SOURCE_REVIEW_REQUIRED` พร้อม region/page จริง ห้ามปลอมเป็น translation failure
7. detector coverage ใหม่ต้องทำ shadow mode จน false-positive rate ผ่านเกณฑ์ จึงค่อยมีสิทธิ์ hard block publication

## P6 — Completeness และ atomic publication

งานที่รายงานว่าสำเร็จต้องผ่านทั้งหมด:

- expected stable region IDs = approved region IDs
- missing translations = 0
- hard quality failures = 0
- empty Thai = 0
- English leakage = 0
- duplicate active translations = 0
- render instructions ต่อ region = 1
- provider/model crossover = 0

หากยังไม่ครบ:

1. ห้าม upload/replace chapter แบบ partial
2. เก็บ checkpoint และ resume เฉพาะ unresolved regions
3. UI แสดงจำนวนและสาเหตุแยกตาม translation, source OCR, provider transport และ cost limit
4. ห้ามลบ valid/approved results และห้ามเริ่มแปลทั้งตอนใหม่
5. สถานะ “สำเร็จ” ใช้ได้เฉพาะหลัง atomic publication สำเร็จจริง

## P7 — Cost control สำหรับ API เสียเงิน

1. แยกค่าใช้จ่าย primary, contract recovery และ semantic repair
2. ทุก paid request ต้อง reserve conservative upper bound ก่อนส่ง และ settle ด้วย actual usage หลังตอบ
3. already-approved region มีต้นทุนเพิ่มเป็นศูนย์
4. ใช้ configurable per-provider chapter cap; ค่าเริ่มต้นทดลองสำหรับ Flash recovery ไม่เกิน `$0.05` ต่อบท แล้วลดจากข้อมูลจริง
5. Pro ต้องมี cap แยกจาก Flash เพราะราคาไม่เท่ากัน
6. call-count cap เป็น safety circuit ไม่ใช่ error message เริ่มต้น; รายงาน `CALL_LIMIT` หรือ `COST_LIMIT` เฉพาะเมื่อชนจริง
7. เมื่อชน cost cap ให้ `PAUSED_COST_LIMIT` พร้อม checkpoint ไม่ใช่ลบงานหรือกล่าวว่า translation error
8. unit/integration/replay tests ห้ามเรียก paid API
9. paid canary ใช้ Chapter 149 หนึ่งรอบหลัง offline tests ผ่าน โดยต้องมี hard cost cap และผู้ใช้เปิดใช้งานอย่างชัดเจน
10. dashboard/log แสดง cost ต่อ request, ต่อ approved region, primary/recovery ratio และจำนวน request ที่หลีกเลี่ยงจากการไม่ resend

## P8 — Performance targets

เป้าหมายสำหรับ Chapter 149 หลัง warm-up:

- Stage 2 primary + recovery median ไม่เกิน 75 วินาที
- Stage 2 hard target ไม่เกิน 100 วินาทีเมื่อไม่มี provider incident
- total chapter median ไม่เกิน 120 วินาทีเมื่อ Stage 1/3 อยู่ใน budget
- repeated identical paid request หลัง contract failure = 0
- recovery request ต้องมี unresolved IDs เท่านั้น
- approved region resend = 0
- Stage 3 AI calls = 0
- UI polling/logging ต้องไม่เพิ่มงาน AI หรือทำให้ UI กระพริบ

การเลือกค่า batch/concurrency ต้องใช้ benchmark completeness, p50/p95 latency, token cost และ contract failure rateร่วมกัน ห้ามเลือกจากความเร็วอย่างเดียว

## P9 — TDD และ verification ก่อน implementation ถือว่าเสร็จ

เขียน test ก่อนแก้โค้ด:

1. Replay รูปแบบงานจริง 89 regions:
   - primary ได้ 76
   - missing จริง 13
   - page diagnostics 20 ต้องไม่ถูกนับเป็น dialogue failure
2. Replay batch partial `17 + 7 missing` และ `10 + 18 missing`
3. HTTP 200 + empty/malformed/truncated JSON ต้องคืน typed outcome ไม่ใช่ generic RuntimeError
4. valid partial results ต้องไม่หายเมื่อ response ส่วนท้ายเสีย
5. adaptive split ต้องลงถึง single ID และจบครบโดยไม่ resend approved IDs
6. quality fixtures สำหรับ clause, negation, number/rank, glossary, gender และ English leakage
7. soft length/style issue ต้องไม่ทำให้คำแปลที่ถูกต้องถูกทิ้ง
8. duplicate response/repair ของ region เดิมต้องมี active translation และ render instruction เดียว
9. snapshot region IDs, boxes และ reading order ก่อน/หลังต้องตรง 100%
10. DeepSeek primary/recovery ทุก call ใช้ provider/model เดิม
11. Groq model switching อยู่ภายใน Groq เท่านั้น
12. cost reservation, call cap, timeout, pause และ resume ทำงานจริง
13. runner/UI terminal status ต้องตรงกับ repository job status
14. full backend tests, integration tests และ touched-code coverage อย่างน้อย 80%
15. visual regression ต้องไม่มี source English ค้าง ไม่มีช่องว่าง และไม่มี Thai overlay ซ้ำ

## ลำดับ implementation สำหรับ model ตัวเล็ก

1. ทำ P0 tests และ snapshot กรอบก่อนแตะ production code
2. ทำ typed outcomes/parser ใน P1 พร้อม replay fixtures
3. ทำ region ledger P2 และย้ายการนับ/attempt/state มาไว้จุดเดียว
4. แยก hard/soft QC ตาม P3
5. ทำ adaptive recovery P4 และ provider assertions
6. ทำ source recovery ภายในกรอบเดิมตาม P5 โดยห้ามเปลี่ยน geometry
7. ทำ atomic publish/checkpoint/cost states ตาม P6–P7
8. ปรับ performance ด้วย benchmark P8 หลัง correctness ผ่านเท่านั้น
9. รัน P9 ทั้งหมด ทำ code review และแก้ P0/P1 findings ก่อน rollout
10. เปิด feature flag ใน shadow/replay → local mock E2E → paid canary 1 บท → rollout ทีละขั้น พร้อม rollback switch

## เกณฑ์เสร็จสมบูรณ์

- Chapter 149 แปลครบทุก stable region ที่กรอบเดิมตรวจพบ
- ไม่มีอังกฤษ ไม่มีช่องว่าง และไม่มีคำแปลซ้ำ
- จำนวน region, `region_id`, พิกัด box และ reading order ไม่เปลี่ยนจาก baseline
- ไม่มี generic RuntimeError หลัง HTTP 200
- ไม่มี payload เดิมวนซ้ำหลัง contract failure
- DeepSeek ไม่ข้าม provider/model และ Groq ไม่ข้าม provider
- คำแปลผ่าน fixtures ด้าน clause, number, rank, negation, glossary, gender และความเป็นธรรมชาติ
- เวลาและค่าใช้จ่ายอยู่ใน budget พร้อมตัวเลขแยก primary/recovery
- job/UI แสดง terminal state และสาเหตุจริง
- regression suite ผ่านทั้งหมดและ code review ไม่มี P0/P1

## Non-goals

- ไม่แก้ bubble detection, grouping, contour, box, mask หรือ reading order
- ไม่ใช้ geometry แก้คำแปลซ้ำ
- ไม่ hardcode ประโยค Chapter 149 ลง production
- ไม่ใช้ AI แปลเพื่อเดา source OCR โดยไม่มี visual evidence
- ไม่เรียก paid API ระหว่าง unit/integration tests
- คำว่า “ครบ 100%” ใน acceptance หมายถึงทุก stable region ที่ระบบกรอบเดิมตรวจพบ; ข้อความที่ระบบไม่เคยตรวจพบต้องถูก coverage audit รายงานแยกอย่างตรงไปตรงมา ไม่ปลอมว่าเป็น translation ID
