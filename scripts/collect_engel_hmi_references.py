"""Collect public ENGEL HMI reference images into a reference-only library.

This script downloads source images from seed pages or explicit image URLs,
de-duplicates by file hash, creates processed PNG copies, writes metadata, and
generates a source-image contact sheet. It is for private visual reference only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required. Install with: python -m pip install Pillow") from exc


ROOT = Path(__file__).resolve().parents[1]
REF_ROOT = ROOT / "assets" / "icon_reference_engel"
RAW_DIR = REF_ROOT / "source_images" / "raw"
PROCESSED_DIR = REF_ROOT / "source_images" / "processed"
CONTACT_DIR = REF_ROOT / "contact_sheets"
METADATA_DIR = REF_ROOT / "metadata"
NOTES_DIR = REF_ROOT / "notes"
SOURCE_META = METADATA_DIR / "source_images.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EOAT-Atlas-reference-collector/1.0"
MIN_IMAGE_AREA = 280 * 180

DEFAULT_SEED_URLS = [
    "https://www.engelglobal.com/en/us/products/injection-molding-machine-controller",
    "https://www.behance.net/gallery/72396149/ENGEL-CC300-Control-Unit?locale=en_US",
]

DEFAULT_SEARCH_TERMS = [
    "ENGEL CC300 HMI icons",
    "ENGEL CC300 interface robot mold icon",
    "ENGEL CC300 control unit screenshot",
    "ENGEL CC300 setup assistant screenshot",
    "ENGEL injection molding machine controller interface",
    "ENGEL machine control robot peripherals mold screenshot",
    "ENGEL CC300 plus control unit touchscreen",
    "ENGEL viper robot CC300 interface",
    "ENGEL mould change setup assistant CC300",
    "ENGEL Spritzeinheit Werkzeugbereich Entformung Roboter Peripherie CC300",
    "ENGEL Rüstassistent CC300 icons",
    "ENGEL Steuerung CC300 Roboter Werkzeugbereich Icons",
]


@dataclass
class SourceImageMeta:
    local_filename: str
    processed_filename: str
    source_url: str
    page_url: str
    page_title: str
    source_domain: str
    downloaded_at: str
    width: int
    height: int
    sha256: str
    notes: str = ""


class ImagePageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.in_title = False
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key.lower(): value or "" for key, value in attrs_list}
        if tag.lower() == "title":
            self.in_title = True
        for key in ("src", "data-src", "data-lazy-src", "data-original", "poster"):
            value = attrs.get(key)
            if value:
                self._add_url(value)
        srcset = attrs.get("srcset") or attrs.get("data-srcset")
        if srcset:
            for item in srcset.split(","):
                candidate = item.strip().split(" ")[0]
                if candidate:
                    self._add_url(candidate)
        for key in ("content", "href"):
            value = attrs.get(key, "")
            if any(ext in value.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                self._add_url(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data.strip())

    def _add_url(self, value: str) -> None:
        value = unescape(value).replace("\\/", "/")
        if value.startswith("//"):
            value = "https:" + value
        absolute = urljoin(self.base_url, value)
        if any(ext in absolute.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
            self.image_urls.append(absolute)

    @property
    def title(self) -> str:
        return " ".join(part for part in self.title_parts if part).strip()


def make_dirs() -> None:
    for folder in (RAW_DIR, PROCESSED_DIR, CONTACT_DIR, METADATA_DIR, NOTES_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def read_existing_metadata() -> list[dict]:
    if SOURCE_META.exists():
        return json.loads(SOURCE_META.read_text(encoding="utf-8"))
    return []


def load_existing_hashes() -> set[str]:
    return {item.get("sha256", "") for item in read_existing_metadata() if item.get("sha256")}


def write_metadata(items: list[SourceImageMeta], skipped: list[dict], search_terms: list[str]) -> None:
    payload = {
        "reference_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "search_terms": search_terms,
        "source_images": [asdict(item) for item in items],
        "skipped": skipped,
    }
    SOURCE_META.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def fetch_url(url: str, timeout: int = 25) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.read()
    except ssl.SSLError:
        context = ssl._create_unverified_context()
        with urlopen(req, timeout=timeout, context=context) as response:
            return response.read()


def fetch_text(url: str) -> tuple[str, str]:
    data = fetch_url(url)
    text = data.decode("utf-8", "replace")
    parser = ImagePageParser(url)
    parser.feed(text)
    return text, parser.title


def extract_image_urls(page_url: str) -> tuple[str, list[str]]:
    html, title = fetch_text(page_url)
    parser = ImagePageParser(page_url)
    parser.feed(html)

    urls = parser.image_urls
    urls.extend(re.findall(r"https?://[^\"'<>\\s]+\\.(?:jpg|jpeg|png|webp)(?:/[^\"'<>\\s]*)?", html, flags=re.I))
    urls = [normalize_image_url(urljoin(page_url, unescape(url).replace("\\/", "/"))) for url in urls]
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen and likely_image_url(url):
            seen.add(url)
            unique.append(url)
    return title or parser.title, unique


def likely_image_url(url: str) -> bool:
    lower = url.lower()
    if not any(ext in lower for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return False
    if any(token in lower for token in ("favicon", "apple-touch-icon", "/tools/", "profile/")):
        return False
    return True


def normalize_image_url(url: str) -> str:
    url = url.strip().replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    # Prefer bigger Storyblok images by removing thumbnail transforms where safe.
    if "a.storyblok.com" in url and "/m/" in url:
        before, _sep, _after = url.partition("/m/")
        url = before
    # Prefer full or 1400 Behance project modules over display thumbnails.
    url = url.replace("/project_modules/disp/", "/project_modules/1400/")
    url = url.replace("/project_modules/disp_webp/", "/project_modules/1400_webp/")
    return url


def safe_slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return slug[:90] or fallback


def extension_from_image(image: Image.Image, url: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".webp"):
        return suffix
    mime = Image.MIME.get(image.format or "")
    return mimetypes.guess_extension(mime or "") or ".png"


def load_image_from_bytes(data: bytes) -> Image.Image:
    image = Image.open(PathBytes(data))
    ImageOps.exif_transpose(image, in_place=True)
    return image.convert("RGBA")


class PathBytes:
    def __init__(self, data: bytes) -> None:
        from io import BytesIO

        self.buffer = BytesIO(data)

    def read(self, *args):
        return self.buffer.read(*args)

    def seek(self, *args):
        return self.buffer.seek(*args)

    def tell(self):
        return self.buffer.tell()


def save_image_from_url(url: str, page_url: str, page_title: str, index: int, hashes: set[str]) -> tuple[SourceImageMeta | None, dict | None]:
    try:
        data = fetch_url(url)
        sha = hashlib.sha256(data).hexdigest()
        if sha in hashes:
            return None, {"source_url": url, "reason": "duplicate_hash"}
        image = load_image_from_bytes(data)
    except (UnidentifiedImageError, OSError, ValueError, TimeoutError, Exception) as exc:
        return None, {"source_url": url, "reason": f"download_or_image_error: {exc}"}

    width, height = image.size
    if width * height < MIN_IMAGE_AREA:
        return None, {"source_url": url, "reason": f"too_small: {width}x{height}"}

    domain = urlparse(url).netloc
    slug = safe_slug(Path(urlparse(url).path).stem, f"source_{index:03d}")
    filename = f"{index:03d}_{slug}_{sha[:10]}.png"
    processed_filename = f"{index:03d}_{slug}_{sha[:10]}_processed.png"
    raw_path = RAW_DIR / filename
    processed_path = PROCESSED_DIR / processed_filename
    image.save(raw_path)
    image.save(processed_path)
    hashes.add(sha)
    return (
        SourceImageMeta(
            local_filename=filename,
            processed_filename=processed_filename,
            source_url=url,
            page_url=page_url,
            page_title=page_title,
            source_domain=domain,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            width=width,
            height=height,
            sha256=sha,
            notes="Reference-only public source image; not a final app asset.",
        ),
        None,
    )


def ingest_manual_images(hashes: set[str], start_index: int) -> tuple[list[SourceImageMeta], list[dict]]:
    items: list[SourceImageMeta] = []
    skipped: list[dict] = []
    existing_meta_names = {item.get("local_filename") for item in read_existing_metadata()}
    manual_files = [
        path
        for path in RAW_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        and path.name not in existing_meta_names
    ]
    index = start_index
    for path in manual_files:
        try:
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if sha in hashes:
                skipped.append({"source_url": str(path), "reason": "duplicate_manual_hash"})
                continue
            image = Image.open(path).convert("RGBA")
            ImageOps.exif_transpose(image, in_place=True)
            width, height = image.size
            processed_filename = f"{index:03d}_{safe_slug(path.stem, 'manual')}_{sha[:10]}_processed.png"
            image.save(PROCESSED_DIR / processed_filename)
            items.append(
                SourceImageMeta(
                    local_filename=path.name,
                    processed_filename=processed_filename,
                    source_url="manual_local_file",
                    page_url="manual_local_file",
                    page_title="Manual local screenshot",
                    source_domain="local",
                    downloaded_at=datetime.now(timezone.utc).isoformat(),
                    width=width,
                    height=height,
                    sha256=sha,
                    notes="Manually placed screenshot; reference-only.",
                )
            )
            hashes.add(sha)
            index += 1
        except Exception as exc:
            skipped.append({"source_url": str(path), "reason": f"manual_ingest_error: {exc}"})
    return items, skipped


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def make_thumbnail(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (255, 255, 255, 0))
    canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def write_source_contact_sheet(items: list[dict]) -> Path:
    columns = 3
    cell_w = 330
    cell_h = 260
    header_h = 78
    rows = max(1, math_ceil(len(items), columns))
    sheet = Image.new("RGBA", (columns * cell_w + 32, header_h + rows * cell_h + 30), (246, 248, 250, 255))
    draw = ImageDraw.Draw(sheet, "RGBA")
    draw.text((24, 20), "ENGEL HMI Source Images", font=load_font(24, True), fill=(30, 42, 50, 255))
    draw.text((24, 50), "REFERENCE ONLY - DO NOT USE AS FINAL APP ASSETS", font=load_font(13, True), fill=(190, 50, 50, 255))
    for index, item in enumerate(items):
        x = 16 + (index % columns) * cell_w
        y = header_h + (index // columns) * cell_h
        draw.rounded_rectangle((x, y, x + cell_w - 12, y + cell_h - 12), radius=8, fill=(255, 255, 255, 255), outline=(214, 222, 228, 255))
        image_path = PROCESSED_DIR / item["processed_filename"]
        if image_path.exists():
            thumb = make_thumbnail(image_path, (cell_w - 42, 178))
            sheet.alpha_composite(thumb, (x + 15, y + 14))
        label = f'{item["local_filename"]}\\n{item["width"]}x{item["height"]}'
        draw.multiline_text((x + 16, y + 204), label, font=load_font(11), fill=(30, 42, 50, 255), spacing=2)
    path = CONTACT_DIR / "source_images_contact_sheet.png"
    sheet.save(path)
    return path


def math_ceil(count: int, divisor: int) -> int:
    return max(1, (count + divisor - 1) // divisor)


def write_notes_stub() -> None:
    ref_notes = NOTES_DIR / "reference_icon_notes.md"
    if not ref_notes.exists():
        ref_notes.write_text(
            "# Reference Icon Notes\n\nNo cropped icons have been generated yet. Add crop boxes and run `python scripts/crop_reference_icons.py --crop`.\n",
            encoding="utf-8",
        )
    style_notes = NOTES_DIR / "visual_style_observations.md"
    if not style_notes.exists():
        style_notes.write_text(
            "# Visual Style Observations\n\nThis file will be updated after reference icons are cropped. Observations should remain broad and must not be used to copy exact proprietary geometry.\n",
            encoding="utf-8",
        )


def write_readme() -> None:
    readme = """# ENGEL HMI Reference Library

This folder is a reference-only collection for studying public ENGEL HMI / CC300 / CC300+ interface screenshots.

It is separate from `assets/icons/`. Do not use any cropped reference images as final EOAT Atlas app icons.

## Folder Layout

- `source_images/raw/` contains downloaded or manually placed source images.
- `source_images/processed/` contains PNG-normalized source images for review.
- `cropped_icons/raw_crops/` contains manually defined icon crops.
- `cropped_icons/normalized/` contains normalized square reference crops.
- `contact_sheets/` contains source and crop contact sheets.
- `metadata/source_images.json` records download metadata.
- `metadata/crop_boxes.json` defines manual crop boxes.
- `metadata/cropped_icons.json` records crop metadata.
- `notes/` contains reference notes and broad style observations.

## Collect Public Source Images

Run:

```powershell
python scripts/collect_engel_hmi_references.py
```

Add more seed pages or image URLs:

```powershell
python scripts/collect_engel_hmi_references.py --seed-url "https://example.com/page" --image-url "https://example.com/image.png"
```

## Add Manual Screenshots

Drop screenshots into:

`assets/icon_reference_engel/source_images/raw/`

Then rerun:

```powershell
python scripts/collect_engel_hmi_references.py --manual-only
```

The script hashes files, adds metadata entries, creates processed PNG copies, and regenerates the source contact sheet.

## Crop Reference Icons

Create a crop template:

```powershell
python scripts/crop_reference_icons.py --write-template
```

Edit:

`assets/icon_reference_engel/metadata/crop_boxes.json`

Then crop:

```powershell
python scripts/crop_reference_icons.py --crop
```

The crops are reference-only and must not be placed in final app UI.
"""
    (REF_ROOT / "README.md").write_text(readme, encoding="utf-8")


def collect(seed_urls: Iterable[str], image_urls: Iterable[str], search_terms: list[str], manual_only: bool = False) -> tuple[list[SourceImageMeta], list[dict]]:
    make_dirs()
    write_notes_stub()
    write_readme()
    existing_payload = read_existing_metadata()
    existing_items = existing_payload.get("source_images", []) if isinstance(existing_payload, dict) else []
    hashes = {item.get("sha256", "") for item in existing_items if item.get("sha256")}
    skipped: list[dict] = existing_payload.get("skipped", []) if isinstance(existing_payload, dict) else []
    collected: list[SourceImageMeta] = []
    index = len(existing_items) + 1

    if not manual_only:
        candidates: list[tuple[str, str, str]] = []
        for page_url in seed_urls:
            try:
                title, urls = extract_image_urls(page_url)
                for url in urls:
                    candidates.append((url, page_url, title))
            except Exception as exc:
                skipped.append({"source_url": page_url, "reason": f"page_crawl_error: {exc}"})
        for url in image_urls:
            candidates.append((normalize_image_url(url), "direct_image_url", "Direct image URL"))

        seen_urls: set[str] = set()
        for url, page_url, page_title in candidates:
            if url in seen_urls:
                skipped.append({"source_url": url, "reason": "duplicate_url_candidate"})
                continue
            seen_urls.add(url)
            meta, skip = save_image_from_url(url, page_url, page_title, index, hashes)
            if meta:
                collected.append(meta)
                index += 1
            if skip:
                skipped.append(skip)

    if manual_only:
        manual_items, manual_skips = ingest_manual_images(hashes, index)
        collected.extend(manual_items)
        skipped.extend(manual_skips)

    all_items = [SourceImageMeta(**item) for item in existing_items if isinstance(item, dict)]
    all_items.extend(collected)
    write_metadata(all_items, skipped, search_terms)
    write_source_contact_sheet([asdict(item) for item in all_items])
    return collected, skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-url", action="append", default=[], help="Seed page URL to crawl for images")
    parser.add_argument("--image-url", action="append", default=[], help="Direct image URL to download")
    parser.add_argument("--search-term", action="append", default=[], help="Search term to record in metadata")
    parser.add_argument("--manual-only", action="store_true", help="Only ingest manually placed images from raw/")
    parser.add_argument("--no-default-seeds", action="store_true", help="Do not use built-in seed pages when no --seed-url is supplied")
    args = parser.parse_args()

    seed_urls = args.seed_url or ([] if args.no_default_seeds else DEFAULT_SEED_URLS)
    search_terms = args.search_term or DEFAULT_SEARCH_TERMS
    collected, skipped = collect(seed_urls, args.image_url, search_terms, manual_only=args.manual_only)

    payload = read_existing_metadata()
    total = len(payload.get("source_images", [])) if isinstance(payload, dict) else len(collected)
    print("ENGEL HMI reference collection summary")
    print(f"- Total source images in metadata: {total}")
    print(f"- Newly collected source images: {len(collected)}")
    print(f"- Skipped candidates: {len(skipped)}")
    print(f"- Source metadata: {SOURCE_META.relative_to(ROOT)}")
    print(f"- Source contact sheet: {(CONTACT_DIR / 'source_images_contact_sheet.png').relative_to(ROOT)}")
    print("- Reference-only folder is separate from assets/icons/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
