#!/usr/bin/env python3
"""Sharpen an image with adjustable enhancement parameters."""
"""USAGE:  python sharpenImage.py input.png
python sharpenImage.py input.png -o out.png --sharpness 3.0 --contrast 1.1"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter


def sharpen_image(
    input_path: Path,
    output_path: Path,
    sharpness: float = 2.5,
    contrast: float = 1.2,
    brightness: float = 1.05,
    unsharp_radius: float = 2.0,
    unsharp_percent: int = 150,
    unsharp_threshold: int = 3,
) -> Path:
    img = Image.open(input_path)

    if sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)

    img = img.filter(
        ImageFilter.UnsharpMask(
            radius=unsharp_radius,
            percent=unsharp_percent,
            threshold=unsharp_threshold,
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Sharpen and enhance an image.")
    p.add_argument("input", type=Path, help="Path to input image")
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output path (default: <input>_sharpened.<ext>)",
    )
    p.add_argument("--sharpness", type=float, default=2.5, help="Sharpness factor (1.0 = no change)")
    p.add_argument("--contrast", type=float, default=1.2, help="Contrast factor (1.0 = no change)")
    p.add_argument("--brightness", type=float, default=1.05, help="Brightness factor (1.0 = no change)")
    p.add_argument("--unsharp-radius", type=float, default=2.0, help="UnsharpMask radius")
    p.add_argument("--unsharp-percent", type=int, default=150, help="UnsharpMask percent")
    p.add_argument("--unsharp-threshold", type=int, default=3, help="UnsharpMask threshold")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if not args.input.is_file():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    output = args.output or args.input.with_name(
        f"{args.input.stem}_sharpened{args.input.suffix}"
    )

    try:
        result = sharpen_image(
            args.input,
            output,
            sharpness=args.sharpness,
            contrast=args.contrast,
            brightness=args.brightness,
            unsharp_radius=args.unsharp_radius,
            unsharp_percent=args.unsharp_percent,
            unsharp_threshold=args.unsharp_threshold,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
