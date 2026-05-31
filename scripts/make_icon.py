from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
target = root / "assets" / "app.ico"
target.parent.mkdir(parents=True, exist_ok=True)

base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(base)
draw.ellipse((24, 24, 232, 232), fill="#2563eb")
draw.rounded_rectangle((101, 52, 155, 151), radius=27, fill="#ffffff")
draw.arc((68, 101, 188, 203), start=0, end=180, fill="#ffffff", width=18)
draw.line((128, 190, 128, 224), fill="#ffffff", width=18)
draw.line((91, 224, 165, 224), fill="#ffffff", width=18)
base.save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
