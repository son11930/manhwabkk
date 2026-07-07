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
        Returns modified copy (immutability rule).
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        draw.rectangle(box, fill=fill_color)
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
