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
        text = re.sub(r'[□■☐☒\u25a0-\u25ff\u200b-\u200f\ufeff\ue000-\uf8ff]', '', text)
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
        text = re.sub(r'\[\s*\]|\(\s*\)|【\s*】|[□■☐☒\u25a0-\u25ff\u200b-\u200f\ufeff\ue000-\uf8ff]', '', text).strip()
        text = re.sub(r'[\[\]\(\)【】]', '', text).strip()
        words = self._normalize_and_tokenize(text)
        if not words:
            return img_copy

        # Erase original text inside the speech bubble box before rendering Thai text
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
            self._draw_thai_line_clean(draw, (x, current_y), shaped_line, font=best_font, fill=text_color)
            current_y += line_height
            
        return img_copy

    def _draw_thai_line_clean(self, draw: ImageDraw.ImageDraw, pos: tuple, text: str, font, fill: tuple) -> None:
        """
        Renders Thai characters cluster-by-cluster, lifting tone marks sitting above upper vowels
        by ~32% of font size so tone marks never sink into upper vowels on systems without HarfBuzz.
        """
        x, y = pos
        shift_y = max(int(getattr(font, "size", 20) * 0.32), 6)
        upper_vowels = {'\u0e31', '\u0e34', '\u0e35', '\u0e36', '\u0e37', '\u0e4d'}
        tone_marks = {'\u0e48', '\u0e49', '\u0e4a', '\u0e4b', '\u0e4c'}
        i = 0
        while i < len(text):
            char = text[i]
            cluster = char
            i += 1
            while i < len(text) and text[i] in upper_vowels.union(tone_marks).union({'\u0e38', '\u0e39'}):
                cluster += text[i]
                i += 1
            
            has_upper = any(c in upper_vowels for c in cluster)
            has_tone = any(c in tone_marks for c in cluster)
            
            if has_upper and has_tone:
                base_part = ''.join(c for c in cluster if c not in tone_marks)
                tone_part = ''.join(c for c in cluster if c in tone_marks)
                draw.text((x, y), base_part, font=font, fill=fill)
                base_char = cluster[0] if cluster else ''
                try:
                    w_base = draw.textlength(base_char, font=font)
                except AttributeError:
                    w_base = getattr(font, "size", 20) * 0.6
                draw.text((x + w_base * 0.64, y - shift_y), tone_part, font=font, fill=fill)
            else:
                draw.text((x, y), cluster, font=font, fill=fill)
            
            try:
                adv = draw.textlength(cluster, font=font)
            except AttributeError:
                adv = len(cluster) * (getattr(font, "size", 20) * 0.5)
            x += adv

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
