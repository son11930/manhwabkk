from typing import Tuple
from PIL import Image, ImageDraw, ImageFont
import textwrap
import io
import os

class TypesetterEngine:
    """
    Typesetter Engine for rendering translated Thai text into speech bubble boxes.
    Handles word wrapping and font scaling.
    """
    def __init__(self, default_font_size: int = 20):
        self.default_font_size = default_font_size
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        # Cross-platform font candidates prioritizing embedded Google Manga fonts
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
        for font_path in font_candidates:
            try:
                self.font = ImageFont.truetype(font_path, size=self.default_font_size)
                break
            except (IOError, OSError):
                continue
        if self.font is None:
            self.font = ImageFont.load_default()

    def render_text_in_box(
        self,
        image: Image.Image,
        text: str,
        box: Tuple[int, int, int, int],
        text_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> Image.Image:
        """
        Renders word-wrapped text centered within the bounding box (left, top, right, bottom).
        Returns a new modified copy of the image.
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        
        left, top, right, bottom = box
        box_width = max(right - left, 10)
        box_height = max(bottom - top, 10)
        
        # Estimate chars per line based on box width
        chars_per_line = max(int(box_width / (self.default_font_size * 0.6)), 5)
        wrapped_lines = textwrap.wrap(text, width=chars_per_line)
        
        # Calculate total text block height
        line_height = self.default_font_size + 4
        total_height = len(wrapped_lines) * line_height
        
        # Start drawing from vertically centered Y coordinate
        current_y = top + max((box_height - total_height) // 2, 0)
        
        for line in wrapped_lines:
            # Center text horizontally
            try:
                bbox = draw.textbbox((0, 0), line, font=self.font)
                line_width = bbox[2] - bbox[0]
            except AttributeError:
                line_width = len(line) * (self.default_font_size // 2)
                
            x = left + max((box_width - line_width) // 2, 0)
            draw.text((x, current_y), line, fill=text_color, font=self.font)
            current_y += line_height
            
        return img_copy

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
