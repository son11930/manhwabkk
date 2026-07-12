from PIL import Image
from src.pipeline.translator import AITranslatorEngine
from src.pipeline.typesetter import TypesetterEngine
from src.pipeline.worker import _SPARE_ME_GREAT_LORD_GLOSSARY


def test_post_process_spacing_fixes_families_to_clan():
    engine = AITranslatorEngine()
    # Point 1: ครอบครัว -> ตระกูล in cultivation context
    raw = "ในอดีต องค์กรและครอบครัวใหญ่ๆ ร่วมมือกันเพื่อป้องกันไม่ให้ผู้ฝึกตนที่ไม่สังกัดเข้าไป"
    processed = engine._post_process_spacing(raw)
    assert "ตระกูลใหญ่" in processed
    assert "ครอบครัวใหญ่" not in processed

    # Verify Spare Me Great Lord glossary includes families/clan terms
    sources = {item["source"].lower(): item["thai"] for item in _SPARE_ME_GREAT_LORD_GLOSSARY}
    assert "families" in sources or "great families" in sources
    assert sources.get("families") == "ตระกูล" or sources.get("great families") == "ตระกูลใหญ่"


def test_typesetter_and_translator_strip_square_boxes_and_tofu():
    engine = AITranslatorEngine()
    # Point 2: มีสี่เหลี่ยม ไม้โท จมอยู่ในวรรณยุคด้วย
    raw = "[]ดี ลีเซียนอี เลื่อนระดับขึ้นเป็นระดับ A □ ■ \u200b"
    processed = engine._post_process_spacing(raw)
    assert "[]" not in processed
    assert "□" not in processed
    assert "■" not in processed
    assert "\u200b" not in processed
    assert processed.startswith("ดี") or "ดี ลีเซียนอี" in processed or "ดี หลี่อี้เซี่ยว" in processed

    # Verify TypesetterEngine renders without throwing and cleans up box characters + tone mark sequence
    typesetter = TypesetterEngine()
    img = Image.new("RGB", (300, 150), (255, 255, 255))
    rendered = typesetter.render_text_in_box(img, "[]ดี ลี้เซียนอี๋ เลื่อนระดับขึ้นเป็นระดับ A", (10, 10, 290, 140))
    assert rendered is not None


def test_post_process_spacing_fixes_water_type_to_element():
    engine = AITranslatorEngine()
    # Point 3: ฉันเป็นประเภทน้ำ -> ฉันเป็นผู้ใช้พลังธาตุน้ำ
    raw = "ฉันเป็นประเภทน้ำ อย่าลืมฉัน ถ้านายเจอของที่เหมาะสม"
    processed = engine._post_process_spacing(raw)
    assert "ฉันเป็นผู้ใช้พลังธาตุน้ำ" in processed or "ฉันเป็นสายธาตุน้ำ" in processed
    assert "ฉันเป็นประเภทน้ำ" not in processed


def test_post_process_spacing_fixes_negative_emotion_value_and_stray_g_letter():
    engine = AITranslatorEngine()
    # Point 4: NEGATIVE EMOTION VALUE ไม่แปล, gนาย, เสียว -> เสี่ยวอวี๋
    raw1 = "NEGATIVE EMOTION VALUE FROM XXX, +100"
    processed1 = engine._post_process_spacing(raw1)
    assert "แต้มอารมณ์ด้านลบ" in processed1 or "ได้รับแต้มอารมณ์ด้านลบ" in processed1

    raw2 = "ฉันด้วย ฉันจะให้ของ gนาย"
    processed2 = engine._post_process_spacing(raw2)
    assert "gนาย" not in processed2
    assert "ของนาย" in processed2

    raw3 = "เสียว นายควรใช้ประโยชน์จากความหนาแน่นรอบๆ ซากปรักหักพัง"
    processed3 = engine._post_process_spacing(raw3)
    assert "เสี่ยว" in processed3
    assert "เสียว" not in processed3


def test_post_process_spacing_strips_vietnamese_nen_and_improves_awkward_phrasing():
    engine = AITranslatorEngine()
    # Point 5: Vietnamese 'nên' leaked, awkward phrasing "ยากลำบากที่จะแย่งชิงเงินของพวกเขา แต่พวกเขาเป็นคนธรรมดาทั่วไปแล้วตอนนี้ nên ควรจะง่ายที่จะปล้นพวกเขา"
    raw = "ในสมัยก่อน นักเรียนหรือเครือข่ายสวรรค์ ยากลำบากที่จะแย่งชิงเงินของพวกเขา แต่พวกเขาเป็นคนธรรมดาทั่วไปแล้วตอนนี้ nên ควรจะง่ายที่จะปล้นพวกเขา"
    processed = engine._post_process_spacing(raw)
    assert "nên" not in processed
    # Verify improved natural scanlator Thai
    assert "แย่งชิงเงินได้ยาก" in processed or "รีดไถเงินได้ยาก" in processed
    assert "ยากลำบากที่จะแย่งชิงเงิน" not in processed


def test_post_process_spacing_converts_thai_rank_spellings_to_uppercase_english():
    engine = AITranslatorEngine()
    raw1 = "หลู่ซู นายแค่ระดับอีเองนะ จะเข้าไปได้ยังไง"
    processed1 = engine._post_process_spacing(raw1)
    assert "ระดับ E" in processed1
    assert "ระดับอี" not in processed1

    raw2 = "ผู้ฝึกตนคลาสเอส เป็นกำลังหลักของตระกูลใหญ่"
    processed2 = engine._post_process_spacing(raw2)
    assert "คลาส S" in processed2
    assert "คลาสเอส" not in processed2


def test_post_process_spacing_fixes_unaffiliated_dragnet_and_phrasing():
    engine = AITranslatorEngine()
    raw1 = "ในอดีตองค์กรและตระกูลต่างๆ ได้รวมกำลังกันเพื่อหยุดผู้ฝึกตนที่สังกัดจากการเข้าไป"
    processed1 = engine._post_process_terminology(raw1)
    assert "ผู้ฝึกตนไร้สังกัด" in processed1
    assert "ผู้ฝึกตนที่สังกัด" not in processed1

    raw2 = "ในอดีตมันเป็นเรื่องของนักศึกษาหรือดรังเนต"
    processed2 = engine._post_process_terminology(raw2)
    assert "เครือข่ายสวรรค์" in processed2
    assert "ดรังเนต" not in processed2

    raw3 = "อืม.. ฉันจะเป็นระดับ D หรือไง?"
    processed3 = engine._post_process_terminology(raw3)
    assert "เหอะ.. คิดว่าฉันเป็นแค่ระดับ D หรือไง?" in processed3

    raw4 = "ไม่รู้เลยว่าเมื่อไหร่พวกเราจะไปถึง C LEVEL นับประสาอะไรกับ B LEVEL"
    processed4 = engine._post_process_terminology(raw4)
    assert "ระดับ C" in processed4
    assert "ระดับ B" in processed4
    assert "C LEVEL" not in processed4
    assert "B LEVEL" not in processed4

    raw5 = "TL/N: ซานซิ่ว คือบริเวณบนเกาะช้าง"
    processed5 = engine._post_process_terminology(raw5)
    assert "หมายเหตุผู้แปล:" in processed5
    assert "TL/N:" not in processed5

    raw7 = "พลังอำในซากปรักหักพังนี้กระจายอย่างสม่ำเสมอมาก นายจะรู้ได้ยังไงว่าข้างไหนคือดวงตาของซากปรักหักพัง?"
    processed7 = engine._post_process_terminology(raw7)
    assert "กระแสพลังในซากปรักหักพัง" in processed7
    assert "แกนกลางของซากปรักหักพัง" in processed7
    assert "พลังอำใน" not in processed7

    raw7b = "พลังอำของซากปรักหักพังนี้รุนแรงมาก"
    processed7b = engine._post_process_terminology(raw7b)
    assert "กระแสพลังของซากปรักหักพัง" in processed7b
    assert "พลังอำ" not in processed7b

    raw8 = "ตอนนี้พวกเขากำลังรวบรวมกำลังใหม่อีกครั้ง□"
    processed8 = engine._post_process_spacing(raw8)
    assert processed8 == "ตอนนี้พวกเขากำลังรวบรวมกำลังใหม่อีกครั้ง"
    assert "□" not in processed8
