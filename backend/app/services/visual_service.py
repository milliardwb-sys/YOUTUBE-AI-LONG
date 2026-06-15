from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.errors import PipelinePreconditionError
from app.models import Project, ProjectStatus, Scene, SourceCandidate
from app.utils.files import ensure_dir
from app.utils.text import wrap_text


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
        for scene in project.scenes:
            slide_path = slides_dir / f"scene_{scene.order:03d}.png"
            source = source_by_id.get(scene.source_id or "")
            if scene.visual_type == "screenshot" and source and source.screenshot_path:
                self._render_source_scene_slide(project, scene, source, slide_path)
            elif scene.visual_type == "table":
                self._render_table_slide(project, scene, slide_path)
            elif scene.visual_type == "diagram":
                self._render_diagram_slide(project, scene, slide_path)
            else:
                self._render_scene_slide(project, scene, slide_path)
            self._verify_slide(slide_path)
            scene.visual_path = str(slide_path)
        project.status = ProjectStatus.visuals_ready
        project.error = None
        project.touch("visuals_ready")
        return project

    def regenerate_scene_slide(self, project: Project, project_dir: Path, scene_id: str) -> Project:
        scene = next((item for item in project.scenes if item.id == scene_id), None)
        if scene is None:
            raise RuntimeError(f"Scene not found: {scene_id}")
        source_by_id = {source.id: source for source in project.sources}
        slide_path = ensure_dir(project_dir / "slides") / f"scene_{scene.order:03d}.png"
        source = source_by_id.get(scene.source_id or "")
        if scene.visual_type == "screenshot" and source and source.screenshot_path:
            self._render_source_scene_slide(project, scene, source, slide_path)
        elif scene.visual_type == "table":
            self._render_table_slide(project, scene, slide_path)
        elif scene.visual_type == "diagram":
            self._render_diagram_slide(project, scene, slide_path)
        else:
            self._render_scene_slide(project, scene, slide_path)
        self._verify_slide(slide_path)
        scene.visual_path = str(slide_path)
        project.touch("scene_slide_regenerated")
        return project

    def _base_image(self, order: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new("RGB", (self.width, self.height), (15, 18, 28))
        draw = ImageDraw.Draw(image)
        self._draw_background(draw, order)
        return image, draw

    def _render_scene_slide(self, project: Project, scene: Scene, path: Path) -> None:
        image, draw = self._base_image(scene.order)
        self._draw_header(draw, project, scene)
        self._draw_body(draw, scene)
        self._draw_avatar_placeholder(draw, project, scene)
        self._draw_footer(draw, project, scene, "original AI slide")
        image.save(path, "PNG", optimize=True)

    def _render_source_scene_slide(
        self, project: Project, scene: Scene, source: SourceCandidate, path: Path
    ) -> None:
        image, draw = self._base_image(scene.order)
        self._draw_header(draw, project, scene)

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
        self._draw_footer(draw, project, scene, "official source preview")
        image.save(path, "PNG", optimize=True)

    def _render_table_slide(self, project: Project, scene: Scene, path: Path) -> None:
        image, draw = self._base_image(scene.order)
        self._draw_header(draw, project, scene)
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
        self._draw_footer(draw, project, scene, "comparison table")
        image.save(path, "PNG", optimize=True)

    def _render_diagram_slide(self, project: Project, scene: Scene, path: Path) -> None:
        image, draw = self._base_image(scene.order)
        self._draw_header(draw, project, scene)
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
        self._draw_footer(draw, project, scene, "process diagram")
        image.save(path, "PNG", optimize=True)

    def _draw_background(self, draw: ImageDraw.ImageDraw, order: int) -> None:
        for y in range(self.height):
            shade = 18 + int(y / self.height * 18)
            draw.line([(0, y), (self.width, y)], fill=(shade, shade + 2, shade + 10))

        accent = (90 + (order * 17) % 90, 110 + (order * 23) % 80, 190)
        draw.rounded_rectangle(
            [self.width - 620, -120, self.width + 120, 520],
            radius=80,
            fill=(accent[0] // 2, accent[1] // 2, accent[2] // 2),
        )
        draw.rounded_rectangle(
            [-140, self.height - 300, 560, self.height + 120],
            radius=70,
            fill=(32, 42, 70),
        )

    def _draw_header(self, draw: ImageDraw.ImageDraw, project: Project, scene: Scene) -> None:
        badge = f"Сцена {scene.order:02d}"
        draw.rounded_rectangle([90, 70, 320, 130], radius=22, fill=(255, 255, 255))
        draw.text((120, 84), badge, font=self.font_small, fill=(20, 24, 36))

        style = project.style.value.replace("_", " ")
        draw.text((350, 84), style, font=self.font_small, fill=(210, 220, 245))
        draw.text((self.width - 430, 84), scene.visual_type, font=self.font_small, fill=(210, 220, 245))

    def _draw_body(self, draw: ImageDraw.ImageDraw, scene: Scene) -> None:
        title_lines = wrap_text(scene.on_screen_text, width=24)
        y = 250
        for line in title_lines[:3]:
            draw.text((110, y), line, font=self.font_title, fill=(255, 255, 255))
            y += 100

        goal_lines = wrap_text(scene.goal.capitalize(), width=52)
        y += 45
        for line in goal_lines[:3]:
            draw.text((116, y), line, font=self.font_regular, fill=(220, 230, 255))
            y += 70

        card_top = 730
        draw.rounded_rectangle(
            [100, card_top, self.width - 100, self.height - 145],
            radius=34,
            fill=(255, 255, 255),
            outline=(230, 235, 255),
            width=2,
        )
        preview = scene.narration[:230] + ("…" if len(scene.narration) > 230 else "")
        preview_lines = wrap_text(preview, width=72)
        y = card_top + 42
        for line in preview_lines[:4]:
            draw.text((150, y), line, font=self.font_small, fill=(35, 42, 60))
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
