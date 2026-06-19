from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
        for scene in project.scenes:
            slide_path = slides_dir / f"scene_{scene.order:03d}.png"
            source = source_by_id.get(scene.source_id or "")
            template = self._template_for_scene(project, scene)
            if scene.visual_type == "screenshot" and source and source.screenshot_path:
                self._render_source_scene_slide(project, scene, source, slide_path, template)
            elif scene.visual_type == "table":
                self._render_table_slide(project, scene, slide_path, template)
            elif scene.visual_type == "diagram":
                self._render_diagram_slide(project, scene, slide_path, template)
            else:
                self._render_scene_slide(project, scene, slide_path, template)
            self._verify_slide(slide_path)
            scene.visual_path = str(slide_path)
            manifest.append(self._template_manifest(scene, template, slide_path))
        write_json(slides_dir / "render_templates.json", manifest)
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
        elif scene.visual_type == "table":
            self._render_table_slide(project, scene, slide_path, template)
        elif scene.visual_type == "diagram":
            self._render_diagram_slide(project, scene, slide_path, template)
        else:
            self._render_scene_slide(project, scene, slide_path, template)
        self._verify_slide(slide_path)
        scene.visual_path = str(slide_path)
        write_json(slides_dir / f"scene_{scene.order:03d}.template.json", self._template_manifest(scene, template, slide_path))
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

    def _draw_header(self, draw: ImageDraw.ImageDraw, project: Project, scene: Scene, template: SlideTemplate) -> None:
        badge = f"Сцена {scene.order:02d}"
        draw.rounded_rectangle([90, 70, 320, 130], radius=22, fill=template.palette["surface"])
        draw.text((120, 84), badge, font=self.font_small, fill=template.palette["surface_text"])

        style = project.style.value.replace("_", " ")
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
        if scene.visual_type == "screenshot":
            return SlideTemplate(
                id="source_review_v1",
                name="Source Review",
                layout="editorial_split",
                palette=palette,
                title_width=22,
                body_width=34,
                footer_label="official source review",
            )
        if scene.visual_type == "table":
            return SlideTemplate(
                id="decision_matrix_v1",
                name="Decision Matrix",
                layout="data_board",
                palette=palette,
                title_width=28,
                body_width=44,
                footer_label="comparison matrix",
            )
        if scene.visual_type == "diagram":
            return SlideTemplate(
                id="workflow_map_v1",
                name="Workflow Map",
                layout="process_map",
                palette=palette,
                title_width=26,
                body_width=46,
                footer_label="process map",
            )
        if project.style.value in {"expert_review", "trend_analysis"}:
            return SlideTemplate(
                id="editorial_brief_v1",
                name="Editorial Brief",
                layout="editorial_split",
                palette=palette,
                title_width=24,
                body_width=52,
                footer_label="editorial brief",
            )
        return SlideTemplate(
            id="studio_focus_v1",
            name="Studio Focus",
            layout="studio_focus",
            palette=palette,
            title_width=25,
            body_width=50,
            footer_label="studio slide",
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
        }

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
