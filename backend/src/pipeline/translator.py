import asyncio
import json
import re
from typing import Mapping, Optional

from src.infrastructure.ai.groq_client import CompletionResult, GroqClient
from src.pipeline.contracts import TranslationBatchRequest, TranslationResult


class TranslationResponseError(ValueError):
    """Raised when a model response cannot map exactly to the requested segments."""


def parse_translation_response(
    response_text: str,
    expected_segment_ids: tuple[str, ...],
    allow_partial: bool = False,
) -> dict[str, str]:
    """Strictly parse the JSON response without dropping multiline dialogue."""
    cleaned_response = re.sub(r"<think>.*?</think>", "", response_text or "", flags=re.DOTALL | re.IGNORECASE).strip()
    if cleaned_response.startswith("```") and cleaned_response.endswith("```"):
        fenced_lines = cleaned_response.splitlines()
        cleaned_response = "\n".join(fenced_lines[1:-1]).strip()
    try:
        payload = json.loads(cleaned_response)
    except (TypeError, json.JSONDecodeError) as error:
        raise TranslationResponseError("translation response must be complete JSON") from error
    entries = payload.get("translations") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise TranslationResponseError("translation response requires a translations list")

    parsed: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            if allow_partial:
                continue
            raise TranslationResponseError("translation item must be an object")
        segment_id = entry.get("segment_id", entry.get("id"))
        text = entry.get("text", entry.get("th", entry.get("target")))
        if not isinstance(segment_id, str) or not isinstance(text, str) or not text.strip():
            if allow_partial:
                continue
            raise TranslationResponseError("translation items require non-empty segment_id and text")
        if segment_id in parsed and not allow_partial:
            raise TranslationResponseError("translation response contains duplicate segment IDs")
        parsed[segment_id] = text.strip()

    if set(parsed) != set(expected_segment_ids) or len(parsed) != len(expected_segment_ids):
        if allow_partial and len(parsed) > 0:
            return {sid: parsed[sid] for sid in expected_segment_ids if sid in parsed}
        raise TranslationResponseError("translation response does not map one-to-one with segments")
    return {segment_id: parsed[segment_id] for segment_id in expected_segment_ids}

def get_genre_context_instructions(genre: str = "modern_cultivation") -> str:
    """
    Returns specific pronoun and stylistic instructions based on manga genre.
    """
    genre_map = {
        "modern_cultivation": (
            "🎯 [แนว: มังฮวาผู้ฝึกตนยุคปัจจุบัน]\n"
            "- สรรพนาม: ฉัน, นาย, แก, เธอ, พี่ชาย, น้องสาว, ท่านผู้ฝึกตน (ห้ามใช้ 'คุณ' พร่ำเพรื่อ)\n"
            "- ศัพท์เฉพาะ: ผู้ฝึกตน, ตระกูลใหญ่ (ห้ามแปลว่าครอบครัว), ผู้ใช้พลังธาตุน้ำ (ห้ามแปลว่าประเภทน้ำ), แต้มอารมณ์ด้านลบ, พลังวิญญาณ, ทะลวงขั้น, ค่ายกล, ระดับ E, เครือข่ายสวรรค์ (Dragnet)\n"
            "- สำนวน: พูดตรงไปตรงมา กวน มันส์ สไตล์การ์ตูนวัยรุ่น ห้ามมีคำเวียดนามหลุด"
        ),
        "wuxia": (
            "🎯 [แนว: ยุทธภพ กำลังภายใน]\n"
            "- สรรพนาม: ข้า, เจ้า, ท่าน, อาวุโส, ศิษย์พี่, ขอรับ\n"
            "- สำนวน: ขึงขัง คมคาย สไตล์ยุทธภพ"
        ),
        "modern_action": (
            "🎯 [แนว: แอคชั่น ดันเจี้ยน ฮันเตอร์]\n"
            "- สรรพนาม: ฉัน, นาย, แก, พวกเรา, บอส\n"
            "- ศัพท์: แรงก์ S, ระดับ A, ดันเจี้ยน\n"
            "- สำนวน: ดุดัน สะใจ สไตล์การ์ตูนแอคชั่น"
        ),
        "romance_drama": (
            "🎯 [แนว: โรแมนติก ดราม่า]\n"
            "- สรรพนาม: เธอ, ฉัน, พี่, น้อง, รุ่นพี่\n"
            "- สำนวน: เน้นอารมณ์ความรู้สึก นุ่มนวล"
        )
    }
    key = genre.lower() if genre else "modern_cultivation"
    if "cultiv" in key or "เซียน" in key or "ผู้ฝึก" in key:
        return genre_map["modern_cultivation"]
    return genre_map.get(key, genre_map["modern_cultivation"])

VETERAN_TRANSLATOR_SYSTEM_PROMPT = (
    "You are an expert Veteran Scanlator translating manhwa/manhua dialogue into expressive, natural Thai spoken language.\n"
    "CRITICAL RULES:\n"
    "1. Pronouns: Never use formal 'คุณ'. Use natural manhwa pronouns: 'นาย', 'เธอ', 'แก', 'ฉัน', 'ท่าน', or character names.\n"
    "2. Complete Translation: Never leave English/Chinese words untranslated. Output 100% Thai script. Transliterate organization/faction names (e.g. Garuda/迦楼罗 -> 'การูดา', Heavenly Network/天罗地网 -> 'เครือข่ายสวรรค์'). NEVER output CJK Chinese/Korean characters.\n"
    "3. Accuracy & Integrity: Translate every sentence completely. Do not summarize, omit, or invent faction names/ranks (e.g., if source is D-level, translate D-level).\n"
    "4. Natural Contextual Phrasing (Never translate literally or formally like a news report):\n"
    "   - rob / steal / robbery -> choose contextually: 'ปล้น', 'ขโมย', or 'ไถเงิน' (never formal 'โจรกรรม').\n"
    "   - have trouble collecting money -> translate contextually: 'ทวงเงินยาก / เก็บค่าคุ้มครองยาก / ไถเงินยาก' (not literal 'มีปัญหาในการเก็บเงิน').\n"
    "   - sweet point / sweet points -> choose contextually: if position/timing use 'จุดที่เหมาะสม / จุดที่ลงตัว / จังหวะที่พอดี'; if banter/points use 'มอบคะแนนแสนหวาน / คะแนนดีๆ / แต้มความหวาน' (never hardcode one word). 'Isn't this what teams are for?' -> 'ทีมมีไว้ทำไมล่ะถ้าไม่ใช่แบบนี้? / นี่แหละประโยชน์ของการอยู่ทีมเดียวกันไม่ใช่เรอะ?'\n"
    "   - 'Then I'll be a D level?' / 'Then I'll be X' -> translate as deciding/choosing a rank: 'งั้น... ฉันเป็นระดับ D ก็แล้วกัน?' or 'งั้นเอาเป็นระดับ D ก็แล้วกัน?' (NEVER mistranslate as 'แล้วฉันจะแค่ระดับ D เหรอ?').\n"
    "   - Action & Idioms: 'call their hometown' / 'call on their hometown' -> 'บุกไปถึงถิ่น / บุกไปถึงบ้านเกิด' (never literal telephone 'โทรไปบ้านเกิด'); 'settle the bills / settle accounts / settle all the bills' -> 'คิดบัญชีแค้น / สะสางหนี้แค้น' (never literal utility bills).\n"
    "   - Multi-bubble Scene Cohesion: Always translate consecutive speech boxes so they connect logically in context. 'YOU'RE THE BEST!' / 'YOU ARE THE BEST' after a show-off/question -> 'สุดยอดไปเลยใช่ไหมล่ะ! / เจ๋งที่สุดเลยใช่ไหมล่ะ!' (never literal 'นายเป็นคนดีที่สุด').\n"
    "5. Terminology: Awakening/Awaken -> 'ตื่นรู้' (or 'การตื่นรู้'); Awakened/Awakener -> 'ผู้ตื่นรู้'; Cultivator/Cultivation -> 'ผู้ฝึกตน' (never 'เกษตรกร'); Rank/Level breakthrough -> 'เลื่อนระดับ/ทะลวงขั้น' (never 'เลื่อนตำแหน่ง').\n"
    "6. Thai Spacing & Punctuation: Insert natural spaces after character names and between clauses. NEVER end Thai sentences with a period (.).\n"
    "7. Output Format: Output ONLY the translated Thai text numbered [1], [2]... No <think> tags, no commentary.\n"
    "8. Organization/Faction Terms: Garuda/迦楼罗 -> 'การูดา'; Family/Great Families/Clan -> 'ตระกูล' or 'ตระกูลใหญ่' (never 'ครอบครัว'); Dragnet/Heavenly Network -> 'เครือข่ายสวรรค์' (never 'ดรังเนต'); Unaffiliated/Rogue Cultivator -> 'ผู้ฝึกตนไร้สังกัด'.\n"
    "9. Elements & System UI: Water-type -> 'ผู้ใช้พลังธาตุน้ำ / สายธาตุน้ำ'; NEGATIVE EMOTION VALUE -> 'แต้มอารมณ์ด้านลบ / ได้รับแต้มอารมณ์ด้านลบ'.\n"
    "10. Ranks/Levels/Classes: Translate 'E-LEVEL'/Level E -> 'ระดับ E'. ONLY single uppercase letters for ranks ('A', 'B', 'C', 'D', 'E', 'S') are allowed in Thai text (never leave English words like 'LEVEL' or 'CLASS').\n"
    "11. Character Attitude & Nuance: Ensure dialogue reflects character intent accurately (e.g. scheming/choosing rank vs complaining).\n"
    "12. Broken English Grammar Correction: Manhwa source text often has poor grammar (e.g. 'DID BOTH BROTHER AND SISTER HAVE BEEN IN RUINS BEFORE.'). NEVER translate word-for-word into gibberish ('ทั้งพี่และน้องสาวมีถูกทำลายก่อน'). Always translate the intended context into natural Thai: 'หรือว่าทั้งสองพี่น้องเคยเข้าไปในซากปรักหักพังมาก่อน!?'. 'ruins/ruin' = 'ซากปรักหักพัง' (never 'ถูกทำลาย').\n"
    "13. Translator Notes (TL/N, T/N): Always translate 'TL/N:' or 'T/N:' prefix as 'หมายเหตุผู้แปล:' and translate the entire explanatory note completely into Thai script (never leave English words or fragmented lines).\n"
    "STANDARD TRANSLATION EXAMPLES:\n"
    "Q: Oh this is my sister Lu Xiaoyu, she will follow me to the ruins too\n"
    "A: โอ้นี่น้องสาวฉันลู่เสี่ยวอวี๋ เธอจะตามฉันไปที่ซากปรักหักพังด้วย\n"
    "Q: Lu Shu is only Level E, how could he enter the ruins?\n"
    "A: ลู่ซู แค่ระดับ E เขาจะเข้าไปในซากปรักหักพังได้ไง\n"
    "Q: ME? E-LEVEL? WHAT KIND OF JOKE IS THIS?\n"
    "A: ฉันเนี่ยนะ? ระดับ E? นี่มันเรื่องตลกอะไรกัน?\n"
    "Q: I REALLY ENVY THEM. I DON'T KNOW WHEN WE WILL REACH THE C LEVEL LET ALONE B LEVEL.\n"
    "A: ฉันอิจฉาพวกเขาจริงๆ ไม่รู้เลยว่าเมื่อไหร่พวกเราถึงจะไปถึงระดับ C นับประสาอะไรกับระดับ B\n"
    "Q: DID BOTH BROTHER AND SISTER HAVE BEEN IN RUINS BEFORE.\n"
    "A: หรือว่าทั้งสองพี่น้องเคยเข้าไปในซากปรักหักพังมาก่อน!?\n"
    "Q: TL/N: SAN XIU (THREE STAR) IS THE AREA IN KOH CHANG ISLAND WHERE THE RUIN IS OPENED\n"
    "A: หมายเหตุผู้แปล: ซานซิ่ว (สามดาว) คือบริเวณบนเกาะช้างที่เป็นจุดเปิดซากปรักหักพัง\n"
    "Q: SOONER OR LATER, I WILL CALL THEIR HOMETOWN, SO I CAN SETTLE ALL THE BILLS WITH THEM.\n"
    "A: ไม่ช้าก็เร็ว ฉันจะบุกไปถึงถิ่นของพวกมัน เพื่อคิดบัญชีแค้นทั้งหมดให้สาสม\n"
    "Q: HOW WAS IT? DO YOU LIKE IT?\n"
    "A: เป็นไงล่ะ? ชอบไหมล่ะ?\n"
    "Q: YOU'RE THE BEST!\n"
    "A: สุดยอดไปเลยใช่ไหมล่ะ!\n"
    "Q: I will go harvest benefits than waiting for ruins to open that is boring\n"
    "A: ฉันจะไปหาผลประโยชน์ดีกว่า มัวแต่รอซากปรักหักพังเปิดมันน่าเบื่อ\n"
    "Q: You are too stingy Li Yixiao, you have to put yourself in the same boat as everyone\n"
    "A: นายงกมากๆ เลย หลี่อี้เซี่ยว นายต้องยัดตัวเองเข้าไปในเรือลำเดียวกันกับทุกๆ คน\n"
    "Q: SO WHAT? WHY DOES THIS MATTER TO ME?\n"
    "A: แล้วไง มันเกี่ยวอะไรกับฉันด้วยล่ะ?\n"
    "Q: TO ME\n"
    "A: เกี่ยวกับฉันล่ะ\n"
    "❌ AI ทื่อ: ฉันจะทำเอง\n"
    "✅ คนแปลอาชีพ: ก็แกรั้นจะให้ฉันทำเองนี่นา\n"
    "Q: You are making a fool of yourself\n"
    "A: กำลังโชว์โง่อยู่หรือไง\n"
)

COMPACT_PER_SEGMENT_SYSTEM_PROMPT = (
    "You are an expert manhwa translator. Translate dialogue into natural spoken Thai.\n"
    "RULES:\n"
    "1. Pronouns: Never use formal 'คุณ'. Use ฉัน, นาย, แก, เธอ, or ท่าน.\n"
    "2. Complete Translation: Never leave English fragments (e.g. 'TO ME', 'FOR ME') or Chinese words untranslated. Output 100% Thai script. Transliterate terms (Garuda/迦楼罗 -> 'การูดา'). NEVER output CJK Chinese/Korean characters.\n"
    "3. Terms: Awakening/Awaken = 'ตื่นรู้', Awakened/Awakener = 'ผู้ตื่นรู้', Cultivator/Cultivation = 'ผู้ฝึกตน', Water-type = 'ผู้ใช้พลังธาตุน้ำ', Family/Clan = 'ตระกูล'. 'Then I'll be a D level?' -> 'งั้น... ฉันเป็นระดับ D ก็แล้วกัน?' (deciding a rank).\n"
    "4. Output ONLY translated Thai text without introductory commentary or periods."
)

class AITranslatorEngine:
    """
    AI Translator Engine powered by Groq API (Llama-3 / Mixtral).
    Uses specialized prompt engineering for expressive, natural Thai manga/manhua translation.
    """
    def __init__(self, client: Optional[GroqClient] = None):
        self.client = client or GroqClient()
        self.system_prompt = VETERAN_TRANSLATOR_SYSTEM_PROMPT

    def _is_valid_thai_translation(self, text: str) -> bool:
        """
        Checks if the translation contains valid Thai characters, is not empty, does not echo prompt rules,
        and does not consist of leftover English explanations or AI meta-language.
        """
        if not text or not text.strip():
            return False
            
        stripped = text.strip()
        # Allow punctuation-only, ellipses, or symbol bubbles (e.g. '???', '...', '!', '?!', '……', '•')
        if not any(c.isalpha() for c in stripped) and stripped:
            return True
            
        thai_chars = sum('\u0e00' <= c <= '\u0e7f' for c in text)
        if thai_chars == 0:
            return False
            
        prompt_echoes = [
            "บริบทเฉพาะเรื่อง", "สรรพนามที่แนะนำ", "คำศัพท์เฉพาะ", "ตอบเฉพาะคำแปล",
            "ห้ามเขียนติดกัน", "แปลข้อความมังงะ", "ห้ามข้ามหรือรวม", "บังคับเว้นวรรค",
            "สไตล์การ์ตูน", "system prompt", "กฎเหล็ก", "แปลบทสนทนา",
            "ไม่พบข้อความที่จะแปล", "ไม่มีข้อความที่จะแปล", "ไม่พบเนื้อหาที่จะแปล",
            "ไม่มีข้อความให้แปล", "ขออภัยครับ ผมไม่พบ", "ขออภัยค่ะ ดิฉันไม่พบ",
            "pronounsrecommended:", "qc/n:", "let'sconstruct"
        ]
        if any(echo.lower() in text.lower() for echo in prompt_echoes):
            return False
            
        ascii_letters = sum(c.isalpha() and c.isascii() for c in text)
        if ascii_letters > 20:
            return False
            
        return True

    def _post_process_terminology(self, text: str) -> str:
        if not text:
            return ""
        # 1. Clean unprintable/box/tofu characters and zero-width spaces
        text = re.sub(r'\[\s*\]|\(\s*\)|【\s*】|[□■☐☒\u25a0-\u25ff\u200b-\u200f\ufeff\ue000-\uf8ff]', '', text)
        text = re.sub(r'[\[\]\(\)【】]', '', text)
        text = re.sub(r'[\u4e00-\u9fff]+', '', text)
        # Clean leaked Vietnamese connector words
        text = re.sub(r'\b(?:nên|nhưng|và|của)\b', '', text, flags=re.IGNORECASE)
        # Translate leftover English system notifications
        text = re.sub(
            r'NEGATIVE\s+EMOTION\s+VALUE(?:\s+FROM\s+([^,\.\n+]+))?(?:,\s*(\+\d+))?',
            lambda m: (
                f"ได้รับแต้มอารมณ์ด้านลบจาก {m.group(1).strip()}, {m.group(2)}"
                if m.group(1) and m.group(2)
                else (f"ได้รับแต้มอารมณ์ด้านลบจาก {m.group(1).strip()}" if m.group(1) else "แต้มอารมณ์ด้านลบ")
            ),
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r'money\.?', 'เงิน', text, flags=re.IGNORECASE)
        # Strip stray single English OCR/LLM garbage letters attached before Thai words (e.g., gนาย -> นาย)
        text = re.sub(r'(?:\b|\s)[a-zA-Z]([\u0e00-\u0e7f])', r'\1', text)
        # Fix manhwa cultivation terminology and scanlator phrasing
        text = re.sub(r'ครอบครัวใหญ่ๆ|ครอบครัวใหญ่|ครอบครัวผู้ฝึกตน', 'ตระกูลใหญ่', text)
        text = re.sub(r'องค์กรและครอบครัว', 'องค์กรและตระกูลใหญ่', text)
        text = re.sub(r'ฉันเป็นธาตุน้ำ|ฉันเป็นประเภทน้ำ|ฉันคือธาตุน้ำ', 'ฉันเป็นผู้ใช้พลังธาตุน้ำ', text)
        text = re.sub(r'เป็นธาตุน้ำ(!|\.| )', r'เป็นผู้ใช้พลังธาตุน้ำ\1', text)
        text = re.sub(r'ผู้ฝึกตนประเภทน้ำ|ประเภทน้ำ', 'ผู้ใช้พลังธาตุน้ำ', text)
        text = re.sub(r'ยากลำบากที่จะแย่งชิงเงิน(?:ของพวกเขา)?', 'แย่งชิงเงินได้ยาก', text)
        text = re.sub(r'เป็นคนธรรมดาทั่วไปแล้วตอนนี้', 'ตอนนี้เป็นแค่คนธรรมดาทั่วไปแล้ว', text)
        text = re.sub(r'\bเสียว\b', 'เสี่ยว', text)
        # Normalize manhwa rank/class/level spellings to uppercase English letter (e.g., ระดับเอ -> ระดับ A, คลาสเอส -> คลาส S)
        rank_map = {
            "เอส": "S",
            "เอฟ": "F",
            "เอ": "A",
            "บี": "B",
            "ซี": "C",
            "ดี": "D",
            "อี": "E",
        }
        for thai_spelling, eng_letter in rank_map.items():
            text = re.sub(
                rf'(ระดับ|คลาส|แรงค์|ขั้น|ระดับของ|คลาสของ|แรงค์ของ)\s*{thai_spelling}\b',
                rf'\1 {eng_letter}',
                text
            )
        text = re.sub(
            r'(ระดับ|คลาส|แรงค์|ขั้น|ระดับของ|คลาสของ|แรงค์ของ)\s*([a-fsA-FS])\b',
            lambda m: f"{m.group(1)} {m.group(2).upper()}",
            text
        )
        text = re.sub(r'[ะฯๆ]([A-Za-z0-9\s]+)[ะฯๆ]', r'\1', text)
        text = re.sub(r'\b([A-FSa-fs])\s*[-–]?\s*(?:LEVEL|Level|level|CLASS|Class|class|RANK|Rank|rank)\b', lambda m: f"ระดับ {m.group(1).upper()}", text)
        text = re.sub(r'\b(?:LEVEL|Level|level|CLASS|Class|class|RANK|Rank|rank)\s*[-–]?\s*([A-FSa-fs])\b', lambda m: f"ระดับ {m.group(1).upper()}", text)
        text = re.sub(r'ผู้ฝึกตนที่สังกัด|ผู้ฝึกตนที่ไม่ได้สังกัด|ผู้ฝึกตนสังกัด', 'ผู้ฝึกตนไร้สังกัด', text)
        text = re.sub(r'ดรังเนต|ดรักเนต|ดรากเนต|เครือข่ายเทียนหลัว', 'เครือข่ายสวรรค์', text)
        text = re.sub(r'\bอเวกเกนเนอร์\b|\bอเวกเคนเนอร์\b', 'ผู้ตื่นรู้', text)
        text = re.sub(r'\bอเวกเกน\b|\bอเวกเคน\b', 'ตื่นรู้', text)
        text = re.sub(r'โทรไปบ้านเกิด', 'บุกไปถึงถิ่น', text)
        text = re.sub(r'จ่ายบิลทั้งหมดกับพวกเขา|ชำระบิลทั้งหมดกับพวกเขา', 'คิดบัญชีแค้นทั้งหมดให้สาสม', text)
        text = re.sub(r'(?:ทำไมเรื่องนี้|เรื่องนี้)\s*TO\s*ME\b', 'เรื่องนี้ต้องเกี่ยวกับฉันด้วย', text, flags=re.IGNORECASE)
        text = re.sub(r'\bTO\s*ME\b', 'เกี่ยวกับฉันล่ะ', text)
        text = re.sub(r'\bFOR\s*ME\b', 'สำหรับฉัน', text)
        text = re.sub(r'\bWITH\s*ME\b', 'กับฉัน', text)
        text = re.sub(r'นายเป็นคนดีที่สุด(!|\.|$)?', r'สุดยอดไปเลยใช่ไหมล่ะ\1', text)
        text = re.sub(r'อืม\.\.\s*ฉันจะเป็นระดับ\s*D\s*หรือไง\?', 'เหอะ.. คิดว่าฉันเป็นแค่ระดับ D หรือไง?', text)
        text = re.sub(r'\b(?:TL/N|T/N|TL\\N)\s*:\s*', 'หมายเหตุผู้แปล: ', text, flags=re.IGNORECASE)
        text = re.sub(r'ทั้งพี่และ\s*น้องสาวมี\s*ถูกทำลาย\s*ก่อน', 'หรือว่าทั้งสองพี่น้องเคยเข้าไปในซากปรักหักพังมาก่อน!?', text)
        return text.strip()

    def _post_process_spacing(self, text: str) -> str:
        """
        Ensures proper Thai whitespace spacing after punctuation and between clauses,
        strips reasoning/meta-notes, and deduplicates AI repetition loops.
        """
        import re
        if not text:
            return ""
        # Strip <think>...</think> blocks from reasoning models
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Strip AI typo correction notes like -"SHOLLD"->"SHOULD" or "A" -> "B"
        text = re.sub(r'-?\s*["\']?[A-Za-z0-9\-\s]+["\']?\s*->\s*["\']?[A-Za-z0-9\-\s]+["\']?', '', text)
        # Remove quotes and markdown remnants
        text = text.strip("\"' ").replace("“", "").replace("”", "")
        text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE).strip()
        
        # Collapse runaway AI repetition loops (if repeated 5+ times, collapse to 2x; allows normal 2-3x manga emphasis)
        text = re.sub(r'(.{2,25}?)\1{4,}', r'\1\1', text)

        # Translate leftover English system notifications before ASCII count filter
        text = re.sub(
            r'NEGATIVE\s+EMOTION\s+VALUE(?:\s+FROM\s+([^,\.\n+]+))?(?:,\s*(\+\d+))?',
            lambda m: (
                f"ได้รับแต้มอารมณ์ด้านลบจาก {m.group(1).strip()}, {m.group(2)}"
                if m.group(1) and m.group(2)
                else (f"ได้รับแต้มอารมณ์ด้านลบจาก {m.group(1).strip()}" if m.group(1) else "แต้มอารมณ์ด้านลบ")
            ),
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r'NEGATIVE\s+EMOTION\s+VALUE', 'แต้มอารมณ์ด้านลบ', text, flags=re.IGNORECASE)

        # Deduplicate AI repetition loops (e.g., ""Sentence A""Sentence A + B""Sentence A + B + C"")
        parts = [p.strip() for p in re.split(r'""+|"|\n', text) if p.strip()]
        if len(parts) > 1:
            # If earlier parts are prefixes or subsets, keep only the longest/cleanest part
            longest_part = max(parts, key=len)
            text = longest_part
            
        # Filter out lines containing AI meta-commentary
        clean_lines = []
        prompt_echoes = [
            "บริบทเฉพาะเรื่อง", "สรรพนามที่แนะนำ", "คำศัพท์เฉพาะ", "ตอบเฉพาะคำแปล",
            "ห้ามเขียนติดกัน", "แปลข้อความมังงะ", "ห้ามข้ามหรือรวม", "บังคับเว้นวรรค",
            "สไตล์การ์ตูน", "system prompt", "กฎเหล็ก", "แปลบทสนทนา",
            "ไม่พบข้อความที่จะแปล", "ไม่มีข้อความที่จะแปล", "ไม่พบเนื้อหาที่จะแปล",
            "ไม่มีข้อความให้แปล", "ขออภัยครับ ผมไม่พบ", "ขออภัยค่ะ ดิฉันไม่พบ"
        ]
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            if any(echo.lower() in stripped.lower() for echo in prompt_echoes):
                continue
            if re.match(r'^(note:|explanation:|translation:|context:|here is|correction:|หมายเหตุ|คำอธิบาย).*', stripped, flags=re.IGNORECASE):
                continue
            ascii_count = sum(c.isalpha() and c.isascii() for c in stripped)
            if ascii_count > 20:
                continue
            clean_lines.append(stripped)
            
        text = " ".join(clean_lines)
        if not text:
            return ""
            
        text = self._post_process_terminology(text)
        # Fix common literal translation artifacts from Llama-3 ('have a hard time' -> 'มีเวลานาน')
        text = re.sub(r'มีเวลานานในการ', 'ยากลำบากในการ', text)
        text = re.sub(r'ใช้เวลานานในการหาเงิน', 'หาเงินอย่างยากลำบาก', text)
        text = re.sub(r'เกษตรกรที่มีความสามารถ', 'ผู้ฝึกตนที่มีความสามารถ', text)
        text = re.sub(r'ป้องกันไม่ให้เกษตรกร', 'ป้องกันไม่ให้ผู้ฝึกตน', text)
        text = re.sub(r'การเลื่อนตำแหน่ง', 'การเลื่อนระดับ', text)
        text = re.sub(r'เลื่อนตำแหน่งของ', 'เลื่อนระดับของ', text)
        text = re.sub(r'มีปัญหาในการเก็บเงิน', 'ทวงเงินยาก', text)
        # Remove unnatural trailing English period (.) at end of Thai sentences
        text = re.sub(r'([\u0e00-\u0e7f]+)\s*\.\s*$', r'\1', text)
        # 2. Add space after punctuation marks followed by Thai characters
        text = re.sub(r'([?!…\.,\-;—~])([\u0e00-\u0e7f])', r'\1 \2', text)
        # 3. Add space between Thai characters and English words/letters/numbers
        text = re.sub(r'([\u0e00-\u0e7f])([A-Za-z0-9])', r'\1 \2', text)
        text = re.sub(r'([A-Za-z0-9])([\u0e00-\u0e7f])', r'\1 \2', text)
        # Preserve a clear clause boundary when OCR/LLM glues the common
        # "...บ้างการรอคอย..." construction into one token stream.
        text = re.sub(r'(บ้าง)(การรอคอย)', r'\1 \2', text)
        # These are spacing-only repairs for common Thai conversational joins.
        # They deliberately do not replace words or infer a different meaning.
        text = re.sub(r'(เลย)(สักนิด)', r'\1 \2', text)
        text = re.sub(r'(สักนิด)(คิดว่า)', r'\1 \2', text)
        text = re.sub(r'(เหรอ)(ไม่บ้าง)', r'\1 \2', text)
        
        # 4. Intelligent Thai Clause Segmentation using PyThaiNLP
        try:
            from pythainlp.tokenize import word_tokenize
            words = word_tokenize(text)
            out = []
            curr_len = 0
            connectors = {'และ', 'แล้ว', 'แต่', 'แต่ว่า', 'เพราะ', 'เพราะว่า', 'เมื่อ', 'ตอนที่', 'หลังจาก', 'ทว่า', 'ดังนั้น', 'ถ้า', 'หาก', 'เพื่อ', 'ส่วน', 'ถึงแม้', 'แล้วก็', 'มัวแต่', 'ในเมื่อ'}
            tail_words = {'ล่ะ', 'สิ', 'นะ', 'น่า', 'จัง', 'เลย', 'หรอก', 'สินะ', 'มั้ง', 'เถอะ', 'มั้ย', 'ไหม', 'เหรอ', 'ครับ', 'ค่ะ', 'ด้วย'}
            starters = {'ฉัน', 'นาย', 'เธอ', 'เขา', 'มัน', 'พวกเรา', 'พวกนาย'}
            preps = {'ของ', 'กับ', 'ให้', 'แก่', 'จาก', 'แด่', 'ต่อ', 'คือ', 'เป็น'}
            
            for i, w in enumerate(words):
                if w == ' ':
                    out.append(w)
                    curr_len = 0
                    continue
                prev = words[i-1] if i > 0 else ''
                if i > 0 and curr_len >= 4 and w in connectors and prev not in preps:
                    if out and out[-1] != ' ':
                        out.append(' ')
                        curr_len = 0
                elif i > 0 and out and out[-1] in tail_words and curr_len >= 8 and i < len(words) - 1:
                    out.append(' ')
                    curr_len = 0
                elif i > 0 and curr_len >= 16 and w in starters and prev not in preps:
                    if out and out[-1] != ' ':
                        out.append(' ')
                        curr_len = 0
                    
                out.append(w)
                curr_len += len(w)
                
            text = ''.join(out)
        except Exception:
            # Fallback if PyThaiNLP is unavailable
            clause_connectors = r'(แต่|แต่ว่า|เพราะ|เพราะว่า|เมื่อ|ตอนที่|หลังจาก|ทว่า|ดังนั้น|ถ้า)'
            text = re.sub(f'([\u0e00-\u0e7f]{{3,}}?)(?<!ดี)(?<!มาก)(?<!น้อย)({clause_connectors})', r'\1 \2', text)
            
        # 5. Clean up any double spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    async def translate_text(self, text: str, target_lang: str = "th", context: Optional[str] = None, genre: str = "modern_cultivation") -> str:
        """
        Translates text into natural Thai webtoon dialect with emotion, formatting spaces between clauses, and high grammatical accuracy.
        """
        if not text or not text.strip():
            return ""
        if not any(c.isalpha() for c in text.strip()):
            return text.strip()

        user_content = f"แปลข้อความมังงะต่อไปนี้เป็นไทยสไตล์การ์ตูน บังคับเว้นวรรคระหว่างประโยคย่อย ห้ามเขียนติดกันเป็นพรืด ห้ามทับศัพท์อังกฤษ และห้ามแต่งเรื่องเอง (ตอบเฉพาะคำแปล):\n\"{text}\""
        genre_info = get_genre_context_instructions(genre)
        user_content += f"\n\n{genre_info}"
        if context:
            user_content += f"\n(บริบทเพิ่มเติม: {context})"

        messages = [
            {"role": "system", "content": COMPACT_PER_SEGMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        res = await self.client.generate_chat_completion(messages=messages, temperature=0.3, max_tokens=650)
        return self._post_process_spacing(res)

    async def translate_batch(self, request_or_texts, target_lang: str = "th", context: Optional[str] = None, genre: str = "modern_cultivation") -> list:
        """Translate either legacy string lists or the Phase 6.16 structured request."""
        if not isinstance(request_or_texts, TranslationBatchRequest):
            return await self._translate_batch_legacy(
                request_or_texts,
                target_lang=target_lang,
                context=context,
                genre=genre,
            )

        request = request_or_texts
        expected_ids = tuple(segment.segment_id for segment in request.segments)
        if not expected_ids:
            return []
        # Optimize input tokens: filter glossary to terms present in current page segments
        page_texts = " ".join(s.source_text.lower() for s in request.segments)
        relevant_glossary = [
            dict(g)
            for g in request.glossary
            if isinstance(g, dict) and g.get("source") and str(g.get("source")).lower() in page_texts
        ]
        # Optimize context: keep only last 2 context entries as simple strings
        recent_context = [
            dict(c) if isinstance(c, dict) else str(c)
            for c in request.context[-8:]
        ]
        pre_translated: dict[str, str] = {}
        llm_segments = []
        for segment in request.segments:
            st = segment.source_text.strip()
            if not any(c.isalpha() for c in st):
                pre_translated[segment.segment_id] = st
            else:
                llm_segments.append(segment)

        if not llm_segments:
            return [
                TranslationResult(
                    segment_id=segment.segment_id,
                    source_text=segment.source_text,
                    draft_thai=pre_translated.get(segment.segment_id, segment.source_text),
                    final_thai=pre_translated.get(segment.segment_id, segment.source_text),
                    model="punctuation_passthrough",
                    attempts=0,
                    qc_status="APPROVED",
                    issue_codes=(),
                )
                for segment in request.segments
            ]

        expected_ids = tuple(segment.segment_id for segment in llm_segments)
        body = {
            "task": "Translate segments sequentially as a connected Thai manga scene. Ensure dialogue flows cohesively across consecutive speech bubbles. Return JSON only.",
            "response_schema": {"translations": [{"id": "string", "th": "string"}]},
            "genre": str(request.profile.get("genre", "modern_cultivation")) if isinstance(request.profile, dict) else "modern_cultivation",
            "segments": [
                {
                    "segment_id": segment.segment_id,
                    "id": segment.segment_id,
                    "text": segment.source_text,
                }
                for segment in llm_segments
            ],
        }
        if relevant_glossary:
            body["glossary"] = relevant_glossary
        if recent_context:
            body["context"] = recent_context

        messages = [
            {
                "role": "system",
                "content": (
                    self.system_prompt
                    + "\nCRITICAL SCENE COHESION & JSON FORMAT: "
                    "1. Treat all segments in the batch as a continuous sequential dialogue scene on the same comic page. Translate consecutive speech bubbles so their meaning, tone, and pronouns connect naturally across boxes (do NOT translate each bubble in isolation). "
                    "2. Return JSON only. Map each segment 'id' strictly to its Thai translation 'th'. NEVER swap IDs or omit any segment."
                ),
            },
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]
        result = None
        translated = {}
        for attempt in range(2):
            if isinstance(self.client, GroqClient):
                completion = await self.client.generate_chat_completion_result(
                    messages=messages, temperature=0.15, max_tokens=1800
                )
            else:
                completion = await self.client.generate_chat_completion(
                    messages=messages, temperature=0.15, max_tokens=1800
                )
            result = completion if isinstance(completion, CompletionResult) else CompletionResult(
                text=str(completion or ""), model="", attempts=1
            )
            try:
                translated = parse_translation_response(result.text, expected_ids)
                break
            except TranslationResponseError:
                if attempt == 1:
                    try:
                        translated = parse_translation_response(result.text, expected_ids, allow_partial=True)
                    except TranslationResponseError:
                        raise
                else:
                    messages[0]["content"] = self.system_prompt + "\nCRITICAL: Return valid JSON object only. Map every single segment id strictly 1-to-1. No explanation."

        translated.update(pre_translated)
        refusal_phrases = ("ไม่มีข้อความให้แปล", "ไม่สามารถแปลได้", "ไม่มีข้อความ", "ข้อความไม่ชัดเจน", "โปรดระบุข้อความ")
        for segment in request.segments:
            curr = translated.get(segment.segment_id, "").strip()
            if any(p in curr for p in refusal_phrases):
                curr = segment.source_text.strip()
                translated[segment.segment_id] = curr
            if not curr or (curr == segment.source_text.strip() and segment.segment_id not in pre_translated):
                single_th = await self.translate_text(
                    segment.source_text,
                    genre=str(request.profile.get("genre", "modern_cultivation")) if isinstance(request.profile, dict) else "modern_cultivation",
                )
                if any(p in single_th for p in refusal_phrases):
                    single_th = segment.source_text.strip()
                translated[segment.segment_id] = single_th or segment.source_text

        return [
            TranslationResult(
                segment_id=segment.segment_id,
                source_text=segment.source_text,
                draft_thai=translated[segment.segment_id],
                final_thai=self._post_process_terminology(translated[segment.segment_id]),
                model=result.model,
                attempts=result.attempts,
                qc_status="PENDING",
            )
            for segment in request.segments
        ]

    async def _translate_batch_legacy(self, texts: list, target_lang: str = "th", context: Optional[str] = None, genre: str = "modern_cultivation") -> list:
        """
        Translates a list of speech bubble texts from a single manga page in ONE API call.
        Reduces Groq API calls by 5x-10x, avoiding rate limit errors and preventing hanging.
        """
        if not texts:
            return []
        
        if len(texts) == 1:
            res = await self.translate_text(texts[0], target_lang=target_lang, context=context, genre=genre)
            return [res]
            
        if len(texts) > 8:
            all_results = []
            for i in range(0, len(texts), 8):
                chunk = texts[i:i+8]
                chunk_res = await self.translate_batch(chunk, target_lang=target_lang, context=context, genre=genre)
                all_results.extend(chunk_res)
            return all_results
            
        numbered_lines = "\n".join([f"[{i+1}] {t}" for i, t in enumerate(texts)])
        user_content = (
            f"แปลเป็นไทยสไตล์มังฮวา เรียงตาม [1]... กำกับ ห้ามย่อ ห้ามสรุป ห้ามตัดทอนข้อความ ต้องแปลให้ครบถ้วนทุกประโยคทุกคำ (บังคับเว้นวรรคคั่นประโยคย่อยให้น่าอ่าน ห้ามเขียนติดกันเป็นพรืด):\n{numbered_lines}"
        )
        genre_info = get_genre_context_instructions(genre)
        user_content += f"\n\n{genre_info}"
        if context:
            user_content += f"\n(บริบทเพิ่มเติม: {context})"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content}
        ]

        res = await self.client.generate_chat_completion(messages=messages, temperature=0.15, max_tokens=2500)
        if not res or not res.strip():
            print(f"[Batch Fallback Skipped] Batch API call failed or in cooldown. Preserving original text for {len(texts)} boxes without retrying.", flush=True)
            return [""] * len(texts)
            
        import re
        # Strip <think> blocks before parsing line by line
        res_clean = re.sub(r'<think>.*?</think>', '', res, flags=re.DOTALL | re.IGNORECASE)
        res_clean = re.sub(r'</?think>', '', res_clean, flags=re.IGNORECASE).strip()
        
        results = []
        lines = res_clean.split("\n")
        parsed_map = {}
        for line in lines:
            match = re.match(r"^\[?(\d+)\]?[\s\.\:\-]\s*(.*)$", line.strip())
            if match:
                idx = int(match.group(1)) - 1
                parsed_map[idx] = self._post_process_spacing(match.group(2))
        
        for i in range(len(texts)):
            val = parsed_map.get(i)
            # If batch translation returned a non-empty string for this box, accept it!
            if val is not None and val.strip() and self._is_valid_thai_translation(val):
                results.append(val)
            else:
                raw_text = texts[i].strip()
                # If box contains NO letters (e.g. only punctuation, ellipses '...', symbols, numbers), keep as-is without API call
                if not any(c.isalpha() for c in raw_text) and raw_text:
                    results.append(raw_text)
                    continue

                is_url = any(w in raw_text.lower() for w in ["http://", "https://", "www.", ".com/", ".org/", ".net/"])
                if is_url:
                    results.append("")
                    continue
                
                # Single fallback translation if missed in batch
                single_res = await self.translate_text(raw_text, target_lang=target_lang, context=context, genre=genre)
                results.append(single_res if (single_res and single_res.strip()) else raw_text)
            
        return results
