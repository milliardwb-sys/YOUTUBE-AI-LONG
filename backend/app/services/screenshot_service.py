from __future__ import annotations

import textwrap
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.models import SourceCandidate
from app.utils.files import ensure_dir
from app.utils.security import validate_source_url


class ScreenshotService:
    """Безопасный screenshot layer.

    По умолчанию он НЕ ходит в интернет и рисует офлайн-карточку источника, чтобы
    весь MVP запускался без браузера и сетевого доступа. Если задать
    ENABLE_BROWSER_SCREENSHOTS=true и установить Playwright, сервис попробует снять
    реальный скриншот URL, а при ошибке вернётся к fallback-card.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.width = settings.render_width
        self.height = settings.render_height
        self.font_title = self._load_font(70)
        self.font_regular = self._load_font(42)
        self.font_small = self._load_font(30)

    def capture_source(self, source: SourceCandidate, output_dir: Path) -> SourceCandidate:
        ensure_dir(output_dir)
        output_path = output_dir / f"{source.id}.png"
        if self.settings.enable_browser_screenshots:
            try:
                self._capture_with_playwright(source.url, output_path)
                source.screenshot_path = str(output_path)
                source.status = "captured"
                source.error = None
                return source
            except Exception as exc:  # noqa: BLE001 - fallback важнее падения MVP
                source.error = f"Browser screenshot failed, fallback card used: {exc}"

        self._render_fallback_source_card(source, output_path)
        source.screenshot_path = str(output_path)
        source.status = "fallback_card"
        return source

    def _capture_with_playwright(self, url: str, output_path: Path) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install optional dependency and run `playwright install chromium`."
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": self.width, "height": self.height})
                validate_source_url(url, self.settings, resolve_dns=True)
                response = page.goto(url, wait_until="networkidle", timeout=self.settings.browser_timeout_ms)
                validate_source_url(page.url, self.settings, resolve_dns=True)
                if response and response.status >= 400:
                    raise RuntimeError(f"Website returned HTTP {response.status}")
                self._try_accept_cookie_banner(page)
                page.screenshot(path=str(output_path), full_page=False)
            finally:
                browser.close()

    def _try_accept_cookie_banner(self, page) -> None:
        candidates = [
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Agree')",
            "button:has-text('Принять')",
            "button:has-text('Согласен')",
            "button:has-text('OK')",
        ]
        for selector in candidates:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=700):
                    locator.click(timeout=700)
                    return
            except Exception:  # noqa: BLE001
                continue

    def _render_fallback_source_card(self, source: SourceCandidate, output_path: Path) -> None:
        image = Image.new("RGB", (self.width, self.height), (245, 247, 252))
        draw = ImageDraw.Draw(image)

        # Browser chrome mock.
        draw.rounded_rectangle([120, 100, self.width - 120, self.height - 120], radius=36, fill=(255, 255, 255))
        draw.rounded_rectangle([120, 100, self.width - 120, 190], radius=36, fill=(235, 239, 247))
        draw.rectangle([120, 150, self.width - 120, 190], fill=(235, 239, 247))
        for x, color in zip([160, 205, 250], [(255, 95, 86), (255, 189, 46), (39, 201, 63)], strict=True):
            draw.ellipse([x, 130, x + 24, 154], fill=color)

        domain = urlparse(source.url).netloc or source.url.replace("https://", "").replace("http://", "")
        draw.rounded_rectangle([320, 124, self.width - 180, 164], radius=18, fill=(255, 255, 255))
        draw.text((350, 128), domain[:70], font=self.font_small, fill=(75, 85, 105))

        # Main hero area.
        draw.rounded_rectangle([190, 260, self.width - 190, 790], radius=38, fill=(17, 24, 39))
        draw.rounded_rectangle([250, 320, 610, 430], radius=28, fill=(99, 102, 241))
        draw.text((290, 345), "OFFICIAL", font=self.font_small, fill=(255, 255, 255))
        draw.text((290, 380), "SOURCE", font=self.font_small, fill=(255, 255, 255))

        title_lines = textwrap.wrap(source.name, width=26)
        y = 475
        for line in title_lines[:3]:
            draw.text((250, y), line, font=self.font_title, fill=(255, 255, 255))
            y += 82

        reason_lines = textwrap.wrap(source.reason, width=62)
        y = 660
        for line in reason_lines[:2]:
            draw.text((250, y), line, font=self.font_regular, fill=(210, 220, 245))
            y += 54

        # Side cards.
        card_x = self.width - 690
        for idx, label in enumerate(["Features", "Pricing", "Docs"]):
            top = 330 + idx * 130
            draw.rounded_rectangle([card_x, top, self.width - 250, top + 88], radius=24, fill=(255, 255, 255))
            draw.text((card_x + 35, top + 24), label, font=self.font_regular, fill=(30, 41, 59))

        draw.text(
            (190, self.height - 190),
            "Fallback preview: enable browser screenshots for real website captures.",
            font=self.font_small,
            fill=(100, 116, 139),
        )
        image.save(output_path, "PNG", optimize=True)

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default()
