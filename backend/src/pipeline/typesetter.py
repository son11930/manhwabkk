from typing import Tuple, List
from PIL import Image, ImageDraw, ImageFont
import io
import os

class TypesetterEngine:
    """
    Typesetter Engine for rendering translated Thai text into speech bubble boxes.
    Handles dictionary-based word wrapping (pythainlp), normalization of tone marks, and dynamic font scaling.
    """
    def __init__(self, default_font_size: int = 20):
        self.default_font_size = default_font_size
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        font_candidates = [
            os.path.join(backend_dir, "assets", "fonts", "Prompt-Regular.ttf"),
            os.path.join(backend_dir, "assets", "fonts", "Sarabun-Regular.ttf"),
            "assets/fonts/Prompt-Regular.ttf",
            "assets/fonts/Sarabun-Regular.ttf",
            "tahoma.ttf",
            "arial.ttf",
            "segoeui.ttf",
            "/usr/share/fonts/truetype/tlwg/Loma.ttf",
            "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
            "/usr/share/fonts/truetype/tlwg/Norasi.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        self.font = None
        self.font_path = None
        for font_path in font_candidates:
            try:
                try:
                    self.font = ImageFont.truetype(font_path, size=self.default_font_size, layout_engine=ImageFont.LAYOUT_RAQM)
                except Exception:
                    self.font = ImageFont.truetype(font_path, size=self.default_font_size)
                self.font_path = font_path
                break
            except (IOError, OSError):
                continue
        if self.font is None:
            self.font = ImageFont.load_default()

    def _normalize_and_tokenize(self, text: str) -> List[str]:
        """
        Normalizes Thai characters (fixes misplaced tone marks/vowels) and tokenizes into words.
        """
        if not text:
            return []
        import re
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\ufeff\ufffd\u25a0-\u25ff□▯。　]', '', text)
        text = re.sub(r'([\u0e00-\u0e7f]+)\s*[\.▪•●◼■_□▯\ufffd]+\s*$', r'\1', text).strip()
        try:
            from pythainlp.util import normalize
            from pythainlp.tokenize import word_tokenize
            clean_text = normalize(text)
            # Use 'newmm' dictionary-based tokenization while preserving all space tokens!
            words = word_tokenize(clean_text, engine="newmm")
            return words
        except Exception:
            # Fallback that preserves spaces between tokens
            import re
            return [w for w in re.split(r'(\s+)', text) if w]

    def _shape_thai_text(self, text: str) -> str:
        """
        Returns normalized Thai text without PUA replacement to prevent square tofu (▯)
        with modern Unicode fonts like Prompt and Sarabun.
        """
        return text

    def _wrap_lines_for_font(self, draw: ImageDraw.ImageDraw, words: List[str], font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
        """
        Packs words into lines without exceeding max_width in pixels, preserving clause spaces.
        """
        lines = []
        current_line = ""
        for word in words:
            test_line = (current_line + word) if current_line else word
            try:
                bbox = draw.textbbox((0, 0), test_line, font=font)
                w = bbox[2] - bbox[0]
            except AttributeError:
                w = len(test_line) * (font.size * 0.6 if hasattr(font, "size") else 10)

            if w <= max_width or not current_line:
                current_line = test_line
            else:
                lines.append(current_line.strip())
                current_line = word.lstrip()
        if current_line.strip():
            lines.append(current_line.strip())
        return lines

    def render_text_in_box(
        self,
        image: Image.Image,
        text: str,
        box: Tuple[int, int, int, int],
        text_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> Image.Image:
        """
        Renders word-wrapped Thai text centered within the bounding box (left, top, right, bottom).
        Uses dynamic font scaling so long sentences fit cleanly inside bubbles without breaking words.
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)

        left, top, right, bottom = box
        box_width = max(right - left, 20)
        box_height = max(bottom - top, 20)
        max_line_width = max(box_width - 12, int(box_width * 0.9))

        import re
        cjk_map = {
            "迦楼罗": "การูดา",
            "天罗地网": "เครือข่ายสวรรค์",
            "聂廷": "เนี่ยถิง",
            "石学晋": "สือเสวียจิ้น",
            "吕": "หลี่",
        }
        for cjk_term, th_val in cjk_map.items():
            text = text.replace(cjk_term, th_val)
        text = re.sub(r'\[\s*\]|\(\s*\)|【\s*】|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f□▯■☐☒。　\u25a0-\u25ff\u200b-\u200f\ufeff\ufffd\ue000-\uf8ff\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af\u3040-\u30ff]', '', text).strip()
        text = re.sub(r'([\u0e00-\u0e7f]+)\s*[\.▪•●◼■_□▯\ufffd]+\s*$', r'\1', text)
        text = re.sub(r'[\[\]\(\)【】]', '', text).strip()
        words = self._normalize_and_tokenize(text)
        if not words:
            return img_copy

        # Cleaning belongs to InpainterEngine. Drawing a second rectangle here
        # can erase artwork when OCR supplied an overly broad box.
        """
        bg_color = (255, 255, 255)
        try:
            sample_points = [
                (left + int(box_width * 0.2), top + int(box_height * 0.15)),
                (left + int(box_width * 0.8), top + int(box_height * 0.15)),
                (left + int(box_width * 0.5), top + int(box_height * 0.10)),
            ]
            valid_colors = []
            for px, py in sample_points:
                if 0 <= px < img_copy.width and 0 <= py < img_copy.height:
                    c = img_copy.getpixel((px, py))
                    if isinstance(c, tuple) and len(c) >= 3:
                        valid_colors.append(c[:3])
            if valid_colors:
                r = sum(c[0] for c in valid_colors) // len(valid_colors)
                g = sum(c[1] for c in valid_colors) // len(valid_colors)
                b = sum(c[2] for c in valid_colors) // len(valid_colors)
                bg_color = (r, g, b)
        except Exception:
            bg_color = (255, 255, 255)

        erase_margin_x = max(int(box_width * 0.05), 4)
        erase_margin_y = max(int(box_height * 0.06), 4)
        erase_box = [
            left + erase_margin_x,
            top + erase_margin_y,
            right - erase_margin_x,
            bottom - erase_margin_y,
        ]
        if erase_box[2] > erase_box[0] and erase_box[3] > erase_box[1]:
            draw.rectangle(erase_box, fill=bg_color)

        """
        # Calculate dynamic start font size based on bubble dimensions so large bubbles get large text
        start_size = max(18, min(int(box_height * 0.28), int(box_width * 0.16), 34))
        best_font = self.font
        best_lines = []
        best_size = start_size

        for size in range(start_size, 12, -2):
            if self.font_path:
                try:
                    current_font = ImageFont.truetype(self.font_path, size=size)
                except Exception:
                    current_font = self.font
            else:
                current_font = self.font

            lines = self._wrap_lines_for_font(draw, words, current_font, max_line_width)
            line_height = int(size * 1.60)
            total_height = len(lines) * line_height

            best_font = current_font
            best_lines = lines
            best_size = size

            # Ensure safety margin so Thai upper tone marks never hit the top of bubble!
            if total_height <= max(box_height - int(size * 0.55), int(box_height * 0.85)):
                break

        line_height = int(best_size * 1.60)
        total_height = len(best_lines) * line_height
        current_y = top + max((box_height - total_height) // 2, max(int(best_size * 0.75), 14))

        for line in best_lines:
            shaped_line = self._shape_thai_text(line)
            try:
                bbox = draw.textbbox((0, 0), shaped_line, font=best_font)
                line_width = bbox[2] - bbox[0]
            except AttributeError:
                line_width = len(shaped_line) * (best_size // 2)
                
            x = left + max((box_width - line_width) // 2, 2)
            self._draw_thai_line_clean(draw, (x, current_y), shaped_line, best_font, text_color)
            current_y += line_height
            
        return img_copy

    def _draw_thai_line_clean(self, draw: ImageDraw.ImageDraw, pos: tuple, text: str, font, fill: tuple) -> None:
        """
        Renders a full line of Thai text cleanly, elevating tone marks above upper vowels on systems without RAQM layout.
        """
        upper_vowels = set("ัิีึื")
        tone_marks = set("่้๊๋์")
        
        # If RAQM is available or no tone marks follow upper vowels, draw directly
        has_vowel_tone_collision = any(
            i > 0 and text[i] in tone_marks and text[i-1] in upper_vowels
            for i in range(len(text))
        )
        if not has_vowel_tone_collision:
            draw.text(pos, text, font=font, fill=fill)
            return

        x, y = pos
        size = getattr(font, "size", 20)
        tone_dy = -int(size * 0.26)
        
        i = 0
        while i < len(text):
            ch = text[i]
            if i > 0 and ch in tone_marks and text[i-1] in upper_vowels:
                draw.text((x, y + tone_dy), ch, font=font, fill=fill)
                i += 1
                continue
            
            # Group contiguous non-elevated characters
            j = i + 1
            while j < len(text) and not (text[j] in tone_marks and text[j-1] in upper_vowels):
                j += 1
            chunk = text[i:j]
            draw.text((x, y), chunk, font=font, fill=fill)
            try:
                bbox = draw.textbbox((0, 0), chunk, font=font)
                x += bbox[2] - bbox[0]
            except AttributeError:
                x += len(chunk) * (size // 2)
            i = j

    def typeset_image(self, image_bytes: bytes, translations: list) -> bytes:
        """
        Applies a list of translations [{'box': (l,t,r,b), 'text': 'thai text'}] to image bytes.
        """
        img = Image.open(io.BytesIO(image_bytes))
        for item in translations:
            img = self.render_text_in_box(img, item["text"], item["box"])
            
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=95)
        return output.getvalue()
