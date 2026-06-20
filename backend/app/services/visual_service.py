from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.errors import PipelinePreconditionError
from app.models import BrandTheme, Project, ProjectStatus, Scene, SourceCandidate
from app.utils.files import ensure_dir, write_json
from app.utils.text import wrap_text


@dataclass(frozen=True)
class SlideTemplate:
    id: str
    name: str
    layout: str
    palette: dict[str, tuple[int, int, int]]
    title_width: int
    body_width: int
    footer_label: str


class VisualService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.width = settings.render_width
        self.height = settings.render_height
        self.font_regular = self._load_font(size=54)
        self.font_title = self._load_font(size=86)
        self.font_small = self._load_font(size=34)
        self.font_tiny = self._load_font(size=25)

    def generate_slides(self, project: Project, project_dir: Path) -> Project:
        if not project.scenes:
            raise PipelinePreconditionError("Script is empty. Run generate-script first.")
        slides_dir = ensure_dir(project_dir / "slides")
        source_by_id = {source.id: source for source in project.sources}
        manifest: list[dict[str, object]] = []
        visual_assets: list[dict[str, object]] = []
        for scene in project.scenes:
            slide_path = slides_dir / f"scene_{scene.order:03d}.png"
            source = source_by_id.get(scene.source_id or "")
            template = self._template_for_scene(project, scene)
            if scene.visual_type == "screenshot" and source and source.screenshot_path:
                self._render_source_scene_slide(project, scene, source, slide_path, template)
            elif scene.visual_type == "screen_demo":
                self._render_screen_demo_slide(project, scene, source, slide_path, template)
            elif scene.visual_type == "avatar_fullscreen":
                self._render_avatar_fullscreen_slide(project, scene, slide_path, template)
            elif scene.visual_type == "avatar_pip":
                self._render_avatar_pip_slide(project, scene, slide_path, template)
            elif scene.visual_type == "ai_broll":
                self._render_ai_broll_slide(project, scene, slide_path, template)
            elif scene.visual_type == "big_caption":
                self._render_big_caption_slide(project, scene, slide_path, template)
            elif scene.visual_type == "cta":
                self._render_cta_slide(project, scene, slide_path, template)
            elif scene.visual_type == "table":
                self._render_table_slide(project, scene, slide_path, template)
            elif scene.visual_type == "diagram":
                self._render_diagram_slide(project, scene, slide_path, template)
            else:
                self._render_scene_slide(project, scene, slide_path, template)
            self._verify_slide(slide_path)
            scene.visual_path = str(slide_path)
            manifest.append(self._template_manifest(scene, template, slide_path))
            visual_assets.append(self._visual_asset_manifest(scene, source))
        write_json(slides_dir / "render_templates.json", manifest)
        visual_assets_path = project_dir / "assets" / "visual_assets_manifest.json"
        write_json(visual_assets_path, visual_assets)
        project.result.visual_assets_manifest_path = str(visual_assets_path)
        project.status = ProjectStatus.visuals_ready
        project.error = None
        project.touch("visuals_ready")
        return project

    def regenerate_scene_slide(self, project: Project, project_dir: Path, scene_id: str) -> Project:
        scene = next((item for item in project.scenes if item.id == scene_id), None)
        if scene is None:
            raise RuntimeError(f"Scene not found: {scene_id}")
        source_by_id = {source.id: source for source in project.sources}
        slides_dir = ensure_dir(project_dir / "slides")
        slide_path = slides_dir / f"scene_{scene.order:03d}.png"
        source = source_by_id.get(scene.source_id or "")
        template = self._template_for_scene(project, scene)
        if scene.visual_type == "screenshot" and source and source.screenshot_path:
            self._render_source_scene_slide(project, scene, source, slide_path, template)
        elif scene.visual_type == "screen_demo":
            self._render_screen_demo_slide(project, scene, source, slide_path, template)
        elif scene.visual_type == "avatar_fullscreen":
            self._render_avatar_fullscreen_slide(project, scene, slide_path, template)
        elif scene.visual_type == "avatar_pip":
            self._render_avatar_pip_slide(project, scene, slide_path, template)
        elif scene.visual_type == "ai_broll":
            self._render_ai_broll_slide(project, scene, slide_path, template)
        elif scene.visual_type == "big_caption":
            self._render_big_caption_slide(project, scene, slide_path, template)
        elif scene.visual_type == "cta":
            self._render_cta_slide(project, scene, slide_path, template)
        elif scene.visual_type == "table":
            self._render_table_slide(project, scene, slide_path, template)
        elif scene.visual_type == "diagram":
            self._render_diagram_slide(project, scene, slide_path, template)
        else:
            self._render_scene_slide(project, scene, slide_path, template)
        self._verify_slide(slide_path)
        scene.visual_path = str(slide_path)
        write_json(slides_dir / f"scene_{scene.order:03d}.template.json", self._template_manifest(scene, template, slide_path))
        write_json(slides_dir / f"scene_{scene.order:03d}.visual_asset.json", self._visual_asset_manifest(scene, source))
        project.touch("scene_slide_regenerated")
        return project

    def _base_image(self, order: int, template: SlideTemplate) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new("RGB", (self.width, self.height), template.palette["background"])
        draw = ImageDraw.Draw(image)
        self._draw_background(draw, order, template)
        return image, draw

    def _render_scene_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        self._draw_body(draw, scene, template)
        self._draw_avatar_placeholder(draw, project, scene)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_source_scene_slide(
        self, project: Project, scene: Scene, source: SourceCandidate, path: Path, template: SlideTemplate
    ) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)

        left_x = 105
        right_x = int(self.width * 0.45)
        y = 235
        draw.text((left_x, y), scene.on_screen_text, font=self.font_title, fill=(255, 255, 255))
        y += 115
        source_label = f"Источник: {source.name}"
        for line in wrap_text(source_label, width=28)[:2]:
            draw.text((left_x, y), line, font=self.font_regular, fill=(222, 230, 255))
            y += 64
        y += 20
        for line in wrap_text(scene.goal.capitalize(), width=35)[:4]:
            draw.text((left_x, y), line, font=self.font_small, fill=(190, 202, 226))
            y += 46

        # Screenshot/browser card.
        screenshot_box = [right_x, 245, self.width - 90, self.height - 155]
        draw.rounded_rectangle(screenshot_box, radius=38, fill=(255, 255, 255), outline=(220, 230, 250), width=3)
        try:
            source_image = Image.open(source.screenshot_path).convert("RGB")
            target_w = screenshot_box[2] - screenshot_box[0] - 40
            target_h = screenshot_box[3] - screenshot_box[1] - 40
            source_image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            paste_x = screenshot_box[0] + 20 + (target_w - source_image.width) // 2
            paste_y = screenshot_box[1] + 20 + (target_h - source_image.height) // 2
            image.paste(source_image, (paste_x, paste_y))
        except Exception:  # noqa: BLE001
            draw.text((screenshot_box[0] + 50, screenshot_box[1] + 70), "Screenshot unavailable", font=self.font_regular, fill=(30, 41, 59))

        # Highlight ribbon.
        draw.rounded_rectangle([left_x, self.height - 285, right_x - 70, self.height - 170], radius=30, fill=(255, 255, 255))
        for line in wrap_text(source.url, width=42)[:2]:
            draw.text((left_x + 35, self.height - 250), line, font=self.font_tiny, fill=(55, 65, 81))

        self._draw_avatar_placeholder(draw, project, scene)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_table_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        draw.text((110, 230), scene.on_screen_text, font=self.font_title, fill=(255, 255, 255))
        rows = self._table_rows(project)
        table_left = 125
        table_top = 410
        table_right = self.width - 125
        col_widths = [390, 360, 360, table_right - table_left - 1110]
        headers = ["Пункт", "Скорость", "Качество", "Кому подходит"]
        x = table_left
        for idx, header in enumerate(headers):
            draw.rounded_rectangle([x, table_top, x + col_widths[idx] - 10, table_top + 74], radius=18, fill=(255, 255, 255))
            draw.text((x + 24, table_top + 18), header, font=self.font_small, fill=(30, 41, 59))
            x += col_widths[idx]
        y = table_top + 94
        for row_index, row in enumerate(rows[:4], start=1):
            x = table_left
            fill = (30, 41, 70) if row_index % 2 else (37, 52, 88)
            for col_index, value in enumerate(row):
                draw.rounded_rectangle([x, y, x + col_widths[col_index] - 10, y + 92], radius=18, fill=fill)
                for line in wrap_text(value, width=20)[:2]:
                    draw.text((x + 24, y + 20), line, font=self.font_tiny, fill=(235, 241, 255))
                    y += 28
                y -= 28 * min(2, len(wrap_text(value, width=20)))
                x += col_widths[col_index]
            y += 112
        self._draw_avatar_placeholder(draw, project, scene)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_diagram_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        draw.text((110, 230), scene.on_screen_text, font=self.font_title, fill=(255, 255, 255))
        steps = ["Тема", "Исследование", "Сцены", "Визуалы", "MP4"]
        top = 520
        block_w = 285
        gap = 65
        x = 110
        for idx, step in enumerate(steps, start=1):
            draw.rounded_rectangle([x, top, x + block_w, top + 170], radius=34, fill=(255, 255, 255))
            draw.text((x + 38, top + 38), f"0{idx}", font=self.font_regular, fill=(99, 102, 241))
            draw.text((x + 38, top + 100), step, font=self.font_small, fill=(30, 41, 59))
            if idx < len(steps):
                arrow_x = x + block_w + 15
                draw.line([arrow_x, top + 85, arrow_x + gap - 30, top + 85], fill=(210, 220, 245), width=7)
                draw.polygon(
                    [(arrow_x + gap - 30, top + 85), (arrow_x + gap - 55, top + 68), (arrow_x + gap - 55, top + 102)],
                    fill=(210, 220, 245),
                )
            x += block_w + gap
        self._draw_avatar_placeholder(draw, project, scene)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_avatar_fullscreen_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        self._draw_avatar_portrait(draw, [self.width - 710, 190, self.width - 135, self.height - 120], fullscreen=True)
        self._draw_caption_words(draw, scene.on_screen_text, [95, 225, self.width - 780, 545], template)
        self._draw_burned_caption(draw, scene.narration, template)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_avatar_pip_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        self._draw_mock_browser(draw, [110, 210, self.width - 110, self.height - 170], scene, template)
        self._draw_pip_avatar(draw, project, scene, x=120, y=self.height - 390)
        self._draw_burned_caption(draw, scene.narration, template)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_screen_demo_slide(
        self,
        project: Project,
        scene: Scene,
        source: SourceCandidate | None,
        path: Path,
        template: SlideTemplate,
    ) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        box = [105, 185, self.width - 95, self.height - 145]
        self._draw_browser_card(draw, box, template)
        if source and source.screenshot_path:
            try:
                source_image = Image.open(source.screenshot_path).convert("RGB")
                self._paste_contained(image, source_image, [box[0] + 32, box[1] + 86, box[2] - 32, box[3] - 32])
            except Exception:  # noqa: BLE001
                self._draw_mock_screen_content(draw, box, scene, template)
        else:
            self._draw_mock_screen_content(draw, box, scene, template)
        self._draw_cursor(draw, self.width - 465, self.height - 355)
        self._draw_pip_avatar(draw, project, scene, x=125, y=self.height - 385)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_ai_broll_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        generated_image_path = self._try_generate_model_image(project, scene, path.parents[1])
        if generated_image_path:
            try:
                generated = Image.open(generated_image_path).convert("RGB")
                self._paste_cover(image, generated, [90, 155, self.width - 90, self.height - 130])
                draw.rounded_rectangle([90, 155, self.width - 90, self.height - 130], radius=40, outline=template.palette["accent"], width=5)
            except Exception as exc:  # noqa: BLE001
                warning = f"Generated image could not be used for scene {scene.order}; template b-roll used: {exc}"
                if warning not in project.result.warnings:
                    project.result.warnings.append(warning)
        center_x = self.width // 2
        center_y = self.height // 2 + 10
        accent = template.palette["accent"]
        for radius, width in [(360, 8), (285, 5), (210, 3)]:
            draw.ellipse(
                [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                outline=(accent[0], accent[1], accent[2]),
                width=width,
            )
        for idx in range(34):
            x = 160 + ((idx * 137) % (self.width - 320))
            y = 210 + ((idx * 83) % (self.height - 420))
            size = 7 + (idx % 4) * 3
            draw.ellipse([x, y, x + size, y + size], fill=(235, 245, 255))
        title = scene.on_screen_text.upper()
        lines = wrap_text(title, width=14)[:2]
        y = center_y - 115
        for line in lines:
            draw.text((center_x - self._text_width(draw, line, self.font_title) // 2, y), line, font=self.font_title, fill=template.palette["title"])
            y += 105
        self._draw_burned_caption(draw, scene.goal.capitalize(), template)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_big_caption_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_caption_words(draw, scene.on_screen_text, [105, 185, self.width - 105, self.height - 260], template, center=True)
        self._draw_burned_caption(draw, scene.narration, template)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _render_cta_slide(self, project: Project, scene: Scene, path: Path, template: SlideTemplate) -> None:
        image, draw = self._base_image(scene.order, template)
        self._draw_header(draw, project, scene, template)
        draw.text((115, 220), "Следующий шаг", font=self.font_small, fill=template.palette["muted_text"])
        y = 275
        for line in wrap_text(scene.on_screen_text, width=22)[:3]:
            draw.text((110, y), line, font=self.font_title, fill=template.palette["title"])
            y += 94
        cta_box = [110, 505, self.width - 110, 760]
        draw.rounded_rectangle(cta_box, radius=34, fill=template.palette["surface"], outline=template.palette["surface_outline"], width=3)
        cta_lines = [
            "1. Напишите в комментариях нишу или AI-инструмент.",
            "2. Сохраните ролик как шаблон для следующего выпуска.",
            "3. Подключите реальный avatar/video provider перед публикацией.",
        ]
        y = cta_box[1] + 45
        for line in cta_lines:
            draw.text((cta_box[0] + 45, y), line, font=self.font_small, fill=template.palette["surface_text"])
            y += 58
        self._draw_pip_avatar(draw, project, scene, x=self.width - 380, y=210)
        self._draw_footer(draw, project, scene, template.footer_label)
        image.save(path, "PNG", optimize=True)

    def _draw_avatar_portrait(self, draw: ImageDraw.ImageDraw, box: list[int], *, fullscreen: bool = False) -> None:
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(box, radius=44 if fullscreen else 26, fill=(245, 247, 251), outline=(255, 255, 255), width=5)
        face_cx = (x1 + x2) // 2
        face_cy = y1 + int((y2 - y1) * 0.34)
        face_r = int((x2 - x1) * 0.16)
        draw.ellipse([face_cx - face_r, face_cy - face_r, face_cx + face_r, face_cy + face_r], fill=(222, 184, 150), outline=(35, 42, 60), width=3)
        draw.arc([face_cx - face_r, face_cy - face_r - 8, face_cx + face_r, face_cy + face_r], 205, 335, fill=(18, 24, 38), width=16)
        shoulder_top = face_cy + face_r + 24
        draw.rounded_rectangle([x1 + 120, shoulder_top, x2 - 120, y2 - 50], radius=70, fill=(17, 24, 39))
        label = "ЦИФРОВОЙ АВАТАР"
        draw.rounded_rectangle([x1 + 65, y2 - 118, x2 - 65, y2 - 58], radius=18, fill=(10, 18, 32))
        draw.text((face_cx - self._text_width(draw, label, self.font_tiny) // 2, y2 - 100), label, font=self.font_tiny, fill=(255, 255, 255))

    def _draw_pip_avatar(self, draw: ImageDraw.ImageDraw, project: Project, scene: Scene, *, x: int, y: int) -> None:
        if not project.avatar_enabled or not scene.avatar_visible:
            return
        w, h = 210, 155
        draw.rounded_rectangle([x - 8, y - 8, x + w + 8, y + h + 8], radius=24, fill=(8, 13, 25))
        draw.rounded_rectangle([x, y, x + w, y + h], radius=20, fill=(235, 238, 244), outline=(255, 255, 255), width=3)
        cx, cy = x + w // 2, y + 58
        draw.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=(222, 184, 150), outline=(28, 36, 52), width=2)
        draw.rounded_rectangle([x + 56, y + 94, x + w - 56, y + h - 8], radius=38, fill=(15, 23, 42))
        draw.rounded_rectangle([x + 18, y + h - 38, x + w - 18, y + h - 8], radius=12, fill=(15, 23, 42))
        draw.text((x + 33, y + h - 35), "AI-ведущий", font=self.font_tiny, fill=(255, 255, 255))

    def _draw_caption_words(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        box: list[int],
        template: SlideTemplate,
        *,
        center: bool = False,
    ) -> None:
        x1, y1, x2, _ = box
        words = wrap_text(text.upper(), width=15)[:4]
        y = y1
        for idx, line in enumerate(words):
            fill = (255, 221, 51) if idx == len(words) - 1 and len(words) > 1 else template.palette["title"]
            x = x1
            if center:
                x = (x1 + x2) // 2 - self._text_width(draw, line, self.font_title) // 2
            draw.text((x, y), line, font=self.font_title, fill=fill, stroke_width=2, stroke_fill=(0, 0, 0))
            y += 105

    def _draw_burned_caption(self, draw: ImageDraw.ImageDraw, text: str, template: SlideTemplate) -> None:
        box = [110, self.height - 235, self.width - 110, self.height - 128]
        draw.rounded_rectangle(box, radius=26, fill=(0, 0, 0), outline=template.palette["accent"], width=3)
        lines = wrap_text(text, width=74)[:2]
        y = box[1] + 22
        for line in lines:
            draw.text((box[0] + 34, y), line, font=self.font_small, fill=(255, 255, 255))
            y += 42

    def _draw_mock_browser(self, draw: ImageDraw.ImageDraw, box: list[int], scene: Scene, template: SlideTemplate) -> None:
        self._draw_browser_card(draw, box, template)
        self._draw_mock_screen_content(draw, box, scene, template)

    def _draw_browser_card(self, draw: ImageDraw.ImageDraw, box: list[int], template: SlideTemplate) -> None:
        draw.rounded_rectangle(box, radius=34, fill=(248, 250, 252), outline=(220, 230, 245), width=3)
        draw.rounded_rectangle([box[0], box[1], box[2], box[1] + 66], radius=34, fill=(235, 240, 248))
        for idx, color in enumerate([(239, 68, 68), (245, 158, 11), (34, 197, 94)]):
            cx = box[0] + 38 + idx * 34
            draw.ellipse([cx - 9, box[1] + 24, cx + 9, box[1] + 42], fill=color)
        draw.rounded_rectangle([box[0] + 150, box[1] + 18, box[2] - 70, box[1] + 48], radius=14, fill=(255, 255, 255))
        draw.text((box[0] + 174, box[1] + 22), "screen-demo.local / proof", font=self.font_tiny, fill=(74, 85, 104))

    def _draw_mock_screen_content(self, draw: ImageDraw.ImageDraw, box: list[int], scene: Scene, template: SlideTemplate) -> None:
        left = box[0] + 45
        top = box[1] + 105
        right = box[2] - 45
        draw.rounded_rectangle([left, top, right, top + 95], radius=22, fill=(15, 23, 42))
        draw.text((left + 32, top + 28), scene.on_screen_text, font=self.font_small, fill=(255, 255, 255))
        y = top + 135
        for idx, line in enumerate(wrap_text(scene.goal.capitalize(), width=64)[:5]):
            fill = (226, 232, 240) if idx % 2 == 0 else (203, 213, 225)
            draw.rounded_rectangle([left, y, right, y + 54], radius=16, fill=fill)
            draw.text((left + 24, y + 13), line, font=self.font_tiny, fill=(30, 41, 59))
            y += 70
        chart_left = right - 420
        chart_top = box[3] - 245
        for idx, height in enumerate([80, 130, 95, 170, 120]):
            x = chart_left + idx * 72
            draw.rounded_rectangle([x, chart_top + 180 - height, x + 42, chart_top + 180], radius=10, fill=template.palette["accent"])

    def _draw_cursor(self, draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
        draw.polygon([(x, y), (x, y + 80), (x + 26, y + 58), (x + 57, y + 122), (x + 86, y + 108), (x + 55, y + 47), (x + 92, y + 45)], fill=(255, 255, 255), outline=(15, 23, 42))
        draw.line([(x + 56, y + 52), (x + 90, y + 122)], fill=(15, 23, 42), width=5)

    def _paste_contained(self, image: Image.Image, source: Image.Image, box: list[int]) -> None:
        target_w = box[2] - box[0]
        target_h = box[3] - box[1]
        source.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        paste_x = box[0] + (target_w - source.width) // 2
        paste_y = box[1] + (target_h - source.height) // 2
        image.paste(source, (paste_x, paste_y))

    def _paste_cover(self, image: Image.Image, source: Image.Image, box: list[int]) -> None:
        target_w = box[2] - box[0]
        target_h = box[3] - box[1]
        scale = max(target_w / source.width, target_h / source.height)
        resized = source.resize((int(source.width * scale), int(source.height * scale)), Image.Resampling.LANCZOS)
        left = max(0, (resized.width - target_w) // 2)
        top = max(0, (resized.height - target_h) // 2)
        cropped = resized.crop((left, top, left + target_w, top + target_h))
        image.paste(cropped, (box[0], box[1]))

    def _try_generate_model_image(self, project: Project, scene: Scene, project_dir: Path) -> Path | None:
        if not self.settings.enable_model_images:
            return None
        output_dir = ensure_dir(project_dir / "assets" / "generated_images")
        output_path = output_dir / f"scene_{scene.order:03d}_model.png"
        if output_path.exists():
            scene.generated_image_path = str(output_path)
            return output_path
        try:
            from openai import OpenAI
        except ImportError as exc:
            warning = f"OpenAI image generation unavailable; install optional dependency: {exc}"
            if warning not in project.result.warnings:
                project.result.warnings.append(warning)
            return None
        try:
            client = OpenAI(api_key=self.settings.openai_api_key)
            prompt = (
                f"{scene.visual_prompt or scene.goal}. "
                f"Original cinematic AI b-roll frame for a Russian YouTube video about {project.topic}. "
                "No logos, no third-party YouTube screenshots, no copyrighted characters. "
                "High contrast, clean tech style, 16:9 composition, space for captions."
            )
            response = client.images.generate(
                model=self.settings.openai_image_model,
                prompt=prompt,
                size=self.settings.openai_image_size,
            )
            first = response.data[0]
            b64_value = getattr(first, "b64_json", None)
            if b64_value:
                output_path.write_bytes(base64.b64decode(b64_value))
            else:
                url_value = getattr(first, "url", None)
                if not url_value:
                    raise RuntimeError("OpenAI image response did not include b64_json or url")
                request = Request(url_value, headers={"User-Agent": "AI Video Studio"})
                with urlopen(request, timeout=60) as response_stream:  # noqa: S310 - URL is provider-returned asset
                    output_path.write_bytes(response_stream.read())
            scene.generated_image_path = str(output_path)
            return output_path
        except Exception as exc:  # noqa: BLE001
            warning = f"Model image generation failed for scene {scene.order}; template b-roll used: {exc}"
            if warning not in project.result.warnings:
                project.result.warnings.append(warning)
            return None

    def _text_width(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _draw_background(self, draw: ImageDraw.ImageDraw, order: int, template: SlideTemplate) -> None:
        for y in range(self.height):
            shade = int(y / self.height * 18)
            base = template.palette["background"]
            draw.line(
                [(0, y), (self.width, y)],
                fill=(
                    min(255, base[0] + shade),
                    min(255, base[1] + shade),
                    min(255, base[2] + shade),
                ),
            )

        accent = template.palette["accent"]
        draw.rounded_rectangle(
            [self.width - 620, -120, self.width + 120, 520],
            radius=80,
            fill=(accent[0] // 2, accent[1] // 2, accent[2] // 2),
        )
        draw.rounded_rectangle(
            [-140, self.height - 300, 560, self.height + 120],
            radius=70,
            fill=template.palette["panel"],
        )
        if template.layout == "editorial_split":
            draw.rounded_rectangle([85, 190, int(self.width * 0.52), self.height - 135], radius=26, outline=accent, width=4)
        elif template.layout == "studio_focus":
            draw.rounded_rectangle([self.width - 520, 210, self.width - 90, self.height - 165], radius=40, fill=template.palette["panel"])
        elif template.layout == "data_board":
            for x in range(120, self.width - 120, 220):
                draw.line([(x, 220), (x, self.height - 170)], fill=template.palette["grid"], width=2)
        elif template.layout == "screen_demo":
            draw.rectangle([0, 150, self.width, self.height - 118], outline=accent, width=5)
        elif template.layout == "avatar_fullscreen":
            draw.rounded_rectangle([self.width - 780, 140, self.width - 70, self.height - 105], radius=48, fill=template.palette["panel"])
        elif template.layout == "big_caption":
            draw.rounded_rectangle([70, 155, self.width - 70, self.height - 250], radius=40, outline=accent, width=8)
        elif template.layout == "ai_broll":
            for x in range(-200, self.width + 220, 180):
                draw.line([(x, 185), (x + 420, self.height - 160)], fill=template.palette["grid"], width=3)
        elif template.layout == "cta":
            draw.rounded_rectangle([80, 185, self.width - 80, self.height - 135], radius=44, outline=accent, width=5)

    def _draw_header(self, draw: ImageDraw.ImageDraw, project: Project, scene: Scene, template: SlideTemplate) -> None:
        badge = f"Сцена {scene.order:02d}"
        draw.rounded_rectangle([90, 70, 320, 130], radius=22, fill=template.palette["surface"])
        draw.text((120, 84), badge, font=self.font_small, fill=template.palette["surface_text"])

        style_labels = {
            "expert_review": "экспертный разбор",
            "tutorial": "обучающий ролик",
            "top_list": "топ-подборка",
            "trend_analysis": "анализ тренда",
            "sales_video": "продающее видео",
            "ai_news_avatar": "AI-ведущий",
        }
        style = style_labels.get(project.style.value, project.style.value.replace("_", " "))
        draw.text((350, 84), style, font=self.font_small, fill=template.palette["muted_text"])
        draw.text((self.width - 560, 84), template.name, font=self.font_small, fill=template.palette["muted_text"])

    def _draw_body(self, draw: ImageDraw.ImageDraw, scene: Scene, template: SlideTemplate) -> None:
        title_lines = wrap_text(scene.on_screen_text, width=template.title_width)
        y = 250
        for line in title_lines[:3]:
            draw.text((110, y), line, font=self.font_title, fill=template.palette["title"])
            y += 100

        goal_lines = wrap_text(scene.goal.capitalize(), width=template.body_width)
        y += 45
        for line in goal_lines[:3]:
            draw.text((116, y), line, font=self.font_regular, fill=template.palette["body"])
            y += 70

        card_top = 730
        draw.rounded_rectangle(
            [100, card_top, self.width - 100, self.height - 145],
            radius=34,
            fill=template.palette["surface"],
            outline=template.palette["surface_outline"],
            width=2,
        )
        preview = scene.narration[:230] + ("…" if len(scene.narration) > 230 else "")
        preview_lines = wrap_text(preview, width=72)
        y = card_top + 42
        for line in preview_lines[:4]:
            draw.text((150, y), line, font=self.font_small, fill=template.palette["surface_text"])
            y += 48

    def _draw_avatar_placeholder(self, draw: ImageDraw.ImageDraw, project: Project, scene: Scene) -> None:
        if not project.avatar_enabled or not scene.avatar_visible:
            return
        size = 160
        margin = 80
        if project.avatar_position == "bottom_left":
            x, y = margin, self.height - margin - size
        elif project.avatar_position == "top_right":
            x, y = self.width - margin - size, 165
        elif project.avatar_position == "top_left":
            x, y = margin, 165
        else:
            x, y = self.width - margin - size, self.height - margin - size
        draw.ellipse([x, y, x + size, y + size], fill=(255, 255, 255), outline=(99, 102, 241), width=6)
        draw.text((x + 42, y + 58), "AV", font=self.font_regular, fill=(30, 41, 59))

    def _draw_footer(self, draw: ImageDraw.ImageDraw, project: Project, scene: Scene, label: str) -> None:
        text = f"AI Video Studio MVP · {label}"
        if scene.source_name:
            text += f" · {scene.source_name}"
        draw.text((100, self.height - 82), text, font=self.font_small, fill=(180, 190, 215))
        duration = f"{scene.duration_sec}s"
        draw.text((self.width - 220, self.height - 82), duration, font=self.font_small, fill=(180, 190, 215))

    def _template_for_scene(self, project: Project, scene: Scene) -> SlideTemplate:
        palette = self._palette_for_theme(project.brand_theme, scene.order)
        if scene.visual_type == "avatar_fullscreen":
            return SlideTemplate(
                id="avatar_fullscreen_v1",
                name="Аватар на весь экран",
                layout="avatar_fullscreen",
                palette=palette,
                title_width=18,
                body_width=42,
                footer_label="аватар на весь экран",
            )
        if scene.visual_type == "avatar_pip":
            return SlideTemplate(
                id="avatar_pip_v1",
                name="Аватар в углу",
                layout="avatar_pip",
                palette=palette,
                title_width=24,
                body_width=52,
                footer_label="picture-in-picture",
            )
        if scene.visual_type == "screen_demo":
            return SlideTemplate(
                id="screen_demo_v1",
                name="Демонстрация экрана",
                layout="screen_demo",
                palette=palette,
                title_width=24,
                body_width=52,
                footer_label="экран и доказательство",
            )
        if scene.visual_type == "ai_broll":
            return SlideTemplate(
                id="ai_broll_v1",
                name="AI-вставка",
                layout="ai_broll",
                palette=palette,
                title_width=18,
                body_width=44,
                footer_label="AI b-roll",
            )
        if scene.visual_type == "big_caption":
            return SlideTemplate(
                id="big_caption_v1",
                name="Крупный хук",
                layout="big_caption",
                palette=palette,
                title_width=16,
                body_width=42,
                footer_label="хук и удержание",
            )
        if scene.visual_type == "cta":
            return SlideTemplate(
                id="cta_v1",
                name="Призыв к действию",
                layout="cta",
                palette=palette,
                title_width=22,
                body_width=46,
                footer_label="CTA",
            )
        if scene.visual_type == "screenshot":
            return SlideTemplate(
                id="source_review_v1",
                name="Разбор источника",
                layout="editorial_split",
                palette=palette,
                title_width=22,
                body_width=34,
                footer_label="источник",
            )
        if scene.visual_type == "table":
            return SlideTemplate(
                id="decision_matrix_v1",
                name="Матрица выбора",
                layout="data_board",
                palette=palette,
                title_width=28,
                body_width=44,
                footer_label="сравнение",
            )
        if scene.visual_type == "diagram":
            return SlideTemplate(
                id="workflow_map_v1",
                name="Карта процесса",
                layout="process_map",
                palette=palette,
                title_width=26,
                body_width=46,
                footer_label="процесс",
            )
        if project.style.value in {"expert_review", "trend_analysis"}:
            return SlideTemplate(
                id="editorial_brief_v1",
                name="Редакционный разбор",
                layout="editorial_split",
                palette=palette,
                title_width=24,
                body_width=52,
                footer_label="разбор",
            )
        return SlideTemplate(
            id="studio_focus_v1",
            name="Студийный слайд",
            layout="studio_focus",
            palette=palette,
            title_width=25,
            body_width=50,
            footer_label="студийный слайд",
        )

    def _palette_for_theme(self, theme: BrandTheme, order: int) -> dict[str, tuple[int, int, int]]:
        accent_shift = (order * 19) % 40
        if theme == BrandTheme.light:
            return {
                "background": (226, 232, 240),
                "panel": (202, 213, 225),
                "grid": (180, 190, 205),
                "accent": (22, 120 + accent_shift, 142),
                "title": (17, 24, 39),
                "body": (51, 65, 85),
                "muted_text": (71, 85, 105),
                "surface": (255, 255, 255),
                "surface_text": (30, 41, 59),
                "surface_outline": (203, 213, 225),
            }
        if theme == BrandTheme.neon:
            return {
                "background": (12, 16, 24),
                "panel": (31, 41, 55),
                "grid": (55, 65, 81),
                "accent": (45 + accent_shift, 212, 191),
                "title": (248, 250, 252),
                "body": (204, 251, 241),
                "muted_text": (186, 230, 253),
                "surface": (240, 253, 250),
                "surface_text": (15, 23, 42),
                "surface_outline": (153, 246, 228),
            }
        return {
            "background": (15, 18, 28),
            "panel": (32, 42, 70),
            "grid": (49, 59, 92),
            "accent": (90 + accent_shift, 128, 190),
            "title": (255, 255, 255),
            "body": (220, 230, 255),
            "muted_text": (210, 220, 245),
            "surface": (255, 255, 255),
            "surface_text": (35, 42, 60),
            "surface_outline": (230, 235, 255),
        }

    def _template_manifest(self, scene: Scene, template: SlideTemplate, slide_path: Path) -> dict[str, object]:
        return {
            "scene_id": scene.id,
            "scene_order": scene.order,
            "visual_type": scene.visual_type,
            "template_id": template.id,
            "template_name": template.name,
            "layout": template.layout,
            "slide_path": slide_path.as_posix(),
            "palette": {key: list(value) for key, value in template.palette.items()},
            "avatar_mode": self._avatar_mode_for_scene(scene),
            "asset_role": self._asset_role_for_scene(scene),
            "montage_note": self._montage_note_for_scene(scene),
        }

    def _visual_asset_manifest(self, scene: Scene, source: SourceCandidate | None) -> dict[str, object]:
        if scene.generated_image_path:
            strategy = "model_generated_image"
        elif scene.visual_type in {"screenshot", "screen_demo"} and source and source.screenshot_path:
            strategy = "platform_screenshot_or_fallback_card"
        else:
            strategy = "offline_render_template"
        return {
            "scene_id": scene.id,
            "scene_order": scene.order,
            "visual_type": scene.visual_type,
            "strategy": strategy,
            "source_id": scene.source_id,
            "source_name": scene.source_name,
            "source_url": scene.source_url,
            "source_screenshot_path": source.screenshot_path if source else None,
            "generated_image_path": scene.generated_image_path,
            "visual_path": scene.visual_path,
            "visual_prompt": scene.visual_prompt,
            "rights_note": (
                "Use user-provided/official platform screenshots or original model-generated images. "
                "Do not use third-party YouTube frames without rights."
            ),
        }

    def _avatar_mode_for_scene(self, scene: Scene) -> str:
        if scene.visual_type == "avatar_fullscreen":
            return "fullscreen"
        if scene.visual_type in {"avatar_pip", "screen_demo", "cta"} and scene.avatar_visible:
            return "picture_in_picture"
        return "none"

    def _asset_role_for_scene(self, scene: Scene) -> str:
        roles = {
            "avatar_fullscreen": "avatar_host",
            "avatar_pip": "talking_head_overlay",
            "screen_demo": "screen_recording_or_source_insert",
            "ai_broll": "generated_broll",
            "big_caption": "retention_caption",
            "cta": "call_to_action",
            "screenshot": "source_screenshot",
            "table": "comparison_table",
            "diagram": "process_diagram",
        }
        return roles.get(scene.visual_type, "original_slide")

    def _montage_note_for_scene(self, scene: Scene) -> str:
        notes = {
            "avatar_fullscreen": "Держать аватар крупно, фон спокойный, субтитр в нижней зоне.",
            "avatar_pip": "Аватар в углу поверх доказательного экрана или карточки.",
            "screen_demo": "Использовать запись экрана, сайт, отчет или fallback-скриншот с курсором.",
            "ai_broll": "Заменить placeholder на AI-видео/анимацию без чужих YouTube-кадров.",
            "big_caption": "Крупная фраза для хука, перехода или главного вывода.",
            "cta": "Финальный призыв: комментарий, подписка, следующий шаг.",
        }
        return notes.get(scene.visual_type, scene.notes or "Стандартная сцена проекта.")

    def _table_rows(self, project: Project) -> list[list[str]]:
        names = [source.name for source in project.sources[:4]] or ["AI-слайды", "Скриншоты", "Озвучка", "Аватар"]
        rows: list[list[str]] = []
        for name in names[:4]:
            rows.append([name, "быстро", "нужно проверить", "авторам и командам"])
        return rows

    def _verify_slide(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                if image.size != (self.width, self.height):
                    raise RuntimeError(f"Slide has wrong size: {path}")
                extrema = image.convert("L").getextrema()
                if extrema[0] == extrema[1]:
                    raise RuntimeError(f"Slide appears blank: {path}")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Slide verification failed for {path}: {exc}") from exc

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
