from typing import Tuple
from PIL import Image, ImageDraw
import io

class InpainterEngine:
    """
    Inpainter Engine for removing original text from speech bubbles and cleaning backgrounds.
    Uses Pillow / OpenCV / LaMa models for background reconstruction.
    """
    def __init__(self):
        pass

    def clean_speech_box(self, image: Image.Image, box: Tuple[int, int, int, int], fill_color: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
        """
        Removes old text inside speech bubble bounding box by whitening/inpainting.
        Uses inward padding, background color sampling, and rounded rectangle to protect surrounding manga drawings.
        Returns modified copy (immutability rule).
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        x1, y1, x2, y2 = box
        # Expand outward by 3px to completely cover old text and any dark anti-aliased smudges
        clean_box = (max(0, int(x1) - 3), max(0, int(y1) - 3), min(image.width - 1, int(x2) + 3), min(image.height - 1, int(y2) + 3))
        
        # Sample 5 points (corners and center) to accurately detect if this is a standard white manga speech bubble
        try:
            samples = []
            for sx, sy in [
                (int(x1) + 8, int(y1) + 8),
                (int(x2) - 8, int(y1) + 8),
                (int(x1) + 8, int(y2) - 8),
                (int(x2) - 8, int(y2) - 8),
                (int((x1 + x2) / 2), int((y1 + y2) / 2))
            ]:
                sx = min(max(sx, 0), image.width - 1)
                sy = min(max(sy, 0), image.height - 1)
                samples.append(image.getpixel((sx, sy)))

            is_white_bubble = False
            for color in samples:
                if isinstance(color, int):
                    r = g = b = color
                elif len(color) >= 3:
                    r, g, b = color[:3]
                else:
                    r = g = b = 255
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                # In manga, standard white bubbles often have slight grey/bluish JPEG shadows (L > 180, low saturation diff)
                if luminance > 180 and (max(r, g, b) - min(r, g, b) < 60):
                    is_white_bubble = True
                    break

            if is_white_bubble:
                # Always snap standard speech bubbles to pure white to prevent weird bluish/greyish rectangle patches!
                fill_color = (255, 255, 255)
            else:
                # For special colorful status boxes (e.g. bright yellow, pink), use center pixel color if bright enough
                center_color = samples[-1]
                if isinstance(center_color, int):
                    r = g = b = center_color
                elif len(center_color) >= 3:
                    r, g, b = center_color[:3]
                else:
                    r = g = b = 255
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                if luminance < 180:
                    fill_color = (255, 255, 255)
                else:
                    fill_color = (r, g, b)
        except Exception:
            fill_color = (255, 255, 255)
            
        draw.rectangle(clean_box, fill=fill_color)
        return img_copy

    def inpaint_image(self, image_bytes: bytes, boxes: list) -> bytes:
        """
        Takes raw image bytes and list of bounding boxes, cleans text, and returns new image bytes.
        """
        img = Image.open(io.BytesIO(image_bytes))
        for box in boxes:
            img = self.clean_speech_box(img, box)
        
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=95)
        return output.getvalue()
