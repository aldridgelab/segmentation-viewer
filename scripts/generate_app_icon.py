"""Generate simple macOS icon assets for the segmentation checker."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def draw_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (11, 13, 16, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    pad = int(size * 0.12)
    draw.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=int(size * 0.15),
        fill=(17, 24, 32, 255),
        outline=(88, 166, 255, 150),
        width=max(2, size // 96),
    )
    draw.rounded_rectangle(
        (int(size * 0.41), int(size * 0.2), int(size * 0.52), int(size * 0.74)),
        radius=int(size * 0.05),
        fill=(88, 166, 255, 230),
    )
    draw.rounded_rectangle(
        (int(size * 0.46), int(size * 0.46), int(size * 0.78), int(size * 0.58)),
        radius=int(size * 0.05),
        fill=(242, 184, 75, 235),
    )
    draw.ellipse(
        (int(size * 0.39), int(size * 0.42), int(size * 0.58), int(size * 0.61)),
        fill=(239, 107, 125, 180),
    )
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", size // 5)
    except OSError:
        font = ImageFont.load_default()
    draw.text((int(size * 0.23), int(size * 0.72)), "SC", fill=(246, 248, 250, 230), font=font)
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("assets"))
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    png_path = output_dir / "app-icon.png"
    source = draw_icon(1024)
    source.save(png_path)

    iconset = output_dir / "app-icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512]
    for size in sizes:
        source.resize((size, size), Image.Resampling.LANCZOS).save(
            iconset / f"icon_{size}x{size}.png"
        )
        source.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
            iconset / f"icon_{size}x{size}@2x.png"
        )

    icns_path = output_dir / "app-icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)], check=True)
    for file_path in iconset.iterdir():
        file_path.unlink()
    iconset.rmdir()
    print(f"png={png_path}")
    print(f"icns={icns_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
