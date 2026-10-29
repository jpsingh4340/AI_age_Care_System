"""Generate clean PNG visuals for AgeCare in Dribbble / MotionSites style.
No SVG. All visuals are saved as crisp, high-DPI PNGs.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "static" / "img"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "ico").mkdir(parents=True, exist_ok=True)

# 1. Google 'G' icon PNG (48x48 supersampled from 192x192)
def make_google_icon():
    S = 4
    size = 48 * S
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Outer circle rings with 4 colors
    cx, cy, r, w = size // 2, size // 2, int(size * 0.42), int(size * 0.18)
    bbox = [cx - r, cy - r, cx + r, cy + r]
    
    # Red (top), Yellow (left), Green (bottom), Blue (right)
    d.arc(bbox, 220, 340, fill=(234, 67, 53, 255), width=w)
    d.arc(bbox, 140, 220, fill=(251, 188, 5, 255), width=w)
    d.arc(bbox, 40, 140, fill=(52, 168, 83, 255), width=w)
    d.arc(bbox, 340, 40, fill=(66, 133, 244, 255), width=w)
    
    # Blue crossbar in center
    bar_w = int(r * 0.95)
    bar_h = w
    d.rectangle([cx, cy - bar_h // 2, cx + bar_w, cy + bar_h // 2], fill=(66, 133, 244, 255))
    
    # Inner cutout to keep G clean
    in_r = r - w
    # smooth downscale
    final = img.resize((48, 48), Image.LANCZOS)
    final.save(OUT / "ico" / "google.png")

# 2. Dribbble-style Dashboard Showcase Graphic (PNG)
def make_showcase_graphic():
    w, h = 900, 500
    img = Image.new("RGBA", (w, h), (246, 245, 242, 255))
    d = ImageDraw.Draw(img)
    
    # Card surface with subtle shadow
    card_box = [30, 24, w - 30, h - 24]
    d.rounded_rectangle(card_box, radius=10, fill=(255, 255, 255, 255), outline=(227, 225, 220, 255), width=2)
    
    # Top clinical header bar
    d.rounded_rectangle([30, 24, w - 30, 80], radius=10, fill=(15, 95, 90, 255))
    d.rectangle([30, 70, w - 30, 80], fill=(15, 95, 90, 255))
    
    # Header text
    d.text((54, 42), "AgeCare Clinical Review · Shift Handover & Priority Triage", fill=(255, 255, 255, 255))
    d.text((w - 200, 42), "Registered Nurse Station", fill=(230, 240, 239, 255))
    
    # 3 Priority cards inside showcase (Red, Amber, Green)
    cards = [
        (54, 104, 300, 240, (161, 40, 31, 255), (253, 240, 239, 255), "Margaret T. (Room 101)", "Red Priority", "SpO2 91% below threshold. Dr called."),
        (324, 104, 570, 240, (138, 90, 0, 255), (253, 246, 231, 255), "Joan P. (Room 103)", "Amber Priority", "Fluid intake 600ml. Carers prompting water."),
        (594, 104, 840, 240, (47, 107, 58, 255), (235, 245, 238, 255), "Ron H. (Room 102)", "Green Priority", "Routine morning care given. Stable vitals.")
    ]
    
    for x0, y0, x1, y1, border_col, bg_col, name, badge, desc in cards:
        d.rounded_rectangle([x0, y0, x1, y1], radius=8, fill=bg_col, outline=border_col, width=2)
        d.text((x0 + 16, y0 + 16), name, fill=(28, 31, 30, 255))
        d.rounded_rectangle([x0 + 16, y0 + 44, x0 + 110, y0 + 68], radius=4, fill=border_col)
        d.text((x0 + 22, y0 + 48), badge, fill=(255, 255, 255, 255))
        d.text((x0 + 16, y0 + 84), desc[:35], fill=(74, 85, 83, 255))
        if len(desc) > 35:
            d.text((x0 + 16, y0 + 104), desc[35:], fill=(74, 85, 83, 255))
            
    # Bottom section: Vital signs mini chart & verified status
    d.rounded_rectangle([54, 260, w - 54, h - 50], radius=8, fill=(255, 255, 255, 255), outline=(227, 225, 220, 255), width=1)
    d.text((74, 280), "Live Vital Signs Trend & Handover Checklist (NZEWS Validated)", fill=(15, 95, 90, 255))
    
    # Grid lines & bars
    vitals = [("Pulse", "78 bpm", 78, (15, 95, 90, 255)), ("BP Systolic", "124 mmHg", 124, (15, 95, 90, 255)), 
              ("Temp", "36.8 °C", 90, (15, 95, 90, 255)), ("SpO2", "98 %", 98, (47, 107, 58, 255))]
    for i, (label, val, bar_len, col) in enumerate(vitals):
        bx = 74 + i * 195
        d.text((bx, 310), label, fill=(115, 128, 125, 255))
        d.text((bx, 330), val, fill=(28, 31, 30, 255))
        d.rounded_rectangle([bx, 356, bx + 150, 364], radius=3, fill=(237, 236, 232, 255))
        d.rounded_rectangle([bx, 356, bx + bar_len, 364], radius=3, fill=col)
        
    img.save(OUT / "preview-dashboard.png", optimize=True)

# 3. Clean role avatars PNG
def make_role_avatars():
    roles = [
        ("role-nurse", (15, 95, 90, 255), "RN"),
        ("role-carer", (35, 120, 115, 255), "CA"),
        ("role-family", (60, 140, 130, 255), "WF"),
        ("role-manager", (10, 69, 65, 255), "MG"),
    ]
    for name, col, text in roles:
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 124, 124], fill=col)
        d.text((42, 48), text, fill=(255, 255, 255, 255))
        img.resize((64, 64), Image.LANCZOS).save(OUT / f"{name}.png")

make_google_icon()
make_showcase_graphic()
make_role_avatars()
print("Created PNG visuals without SVG.")
