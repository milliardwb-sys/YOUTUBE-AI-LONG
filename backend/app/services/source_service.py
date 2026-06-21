from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.models import Project, ProjectStatus, SourceCandidate, SourceKind, VisualMode
from app.services.search_provider import DisabledSearchProvider, SearchProviderUnavailable, make_search_provider
from app.services.screenshot_service import ScreenshotService
from app.services.visual_plan_service import SOURCE_VISUAL_TYPES, VisualPlanDecision, VisualPlanService
from app.utils.files import ensure_dir, write_json
from app.utils.security import UnsafeUrlError, validate_source_url


class SourceService:
    """Исследование безопасных визуальных источников MVP.

    Текущая версия не использует поисковые API, поэтому работает офлайн:
    - берёт URL, указанные пользователем;
    - добавляет curated official websites по ключевым словам темы;
    - создаёт fallback-карточки/скриншоты через ScreenshotService;
    - привязывает источники к screenshot-сценам.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.screenshots = ScreenshotService(settings)
        self.visual_plan = VisualPlanService()
        try:
            self.search_provider = make_search_provider(settings)
        except SearchProviderUnavailable as exc:
            self.search_provider = DisabledSearchProvider()
            self.search_provider_error = str(exc)
        else:
            self.search_provider_error = None

    def collect_sources(self, project: Project, project_dir: Path) -> Project:
        project.status = ProjectStatus.researching
        project.touch("researching_sources")
        plan = self.visual_plan.plan_project(project)

        if project.visual_mode != VisualMode.official_sites_plus_ai and not project.source_urls:
            project.sources = []
            project.result.visual_plan_path = str(self._write_visual_plan(project, project_dir, plan))
            project.touch("sources_skipped")
            return project

        candidates = self._user_sources(project) + self._search_sources(project) + self._curated_sources(project)
        candidates = self._dedupe_sources(candidates)[:8]
        assets_dir = ensure_dir(project_dir / "assets" / "sources")

        captured: list[SourceCandidate] = []
        for source in candidates:
            try:
                validate_source_url(source.url, self.settings, resolve_dns=self.settings.enable_browser_screenshots)
                captured.append(self.screenshots.capture_source(source, assets_dir))
            except UnsafeUrlError as exc:
                source.status = "failed"
                source.error = str(exc)
                captured.append(source)

        project.sources = captured
        self._assign_sources_to_scenes(project)
        project.result.visual_plan_path = str(self._write_visual_plan(project, project_dir, plan))
        project.status = ProjectStatus.sources_ready
        project.touch("sources_ready")
        return project

    def _user_sources(self, project: Project) -> list[SourceCandidate]:
        sources: list[SourceCandidate] = []
        for url in project.source_urls:
            name = self._name_from_url(url)
            sources.append(
                SourceCandidate(
                    name=name,
                    url=url,
                    kind=SourceKind.user_provided,
                    license_note="User-provided source URL; user must confirm publication rights/terms.",
                    reason="Источник добавлен пользователем для этого ролика.",
                )
            )
        return sources

    def _search_sources(self, project: Project) -> list[SourceCandidate]:
        if self.settings.search_result_count <= 0:
            return []
        if self.search_provider_error:
            warning = f"Search provider disabled: {self.search_provider_error}"
            if warning not in project.result.warnings:
                project.result.warnings.append(warning)
            return []
        try:
            results = []
            for query in self._search_queries(project):
                results.extend(
                    self.search_provider.search(
                        query,
                        count=self.settings.search_result_count,
                        language=project.language,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - search must never break local generation
            warning = f"Search provider failed; curated sources were used: {exc}"
            if warning not in project.result.warnings:
                project.result.warnings.append(warning)
            return []
        return [
            SourceCandidate(
                name=result.title,
                url=result.url,
                kind=SourceKind.search_result,
                license_note="Search provider result; verify source terms, rights, and factual accuracy before publication.",
                reason=result.description or "Search provider result for the project topic.",
            )
            for result in results
        ]

    def _curated_sources(self, project: Project) -> list[SourceCandidate]:
        text = f"{project.topic} {project.audience}".lower()
        curated: list[tuple[str, str, str]] = []

        if any(keyword in text for keyword in ["ai", "ии", "видео", "ролик", "avatar", "аватар"]):
            curated.extend(
                [
                    ("HeyGen", "https://www.heygen.com/", "AI-аватары, talking-head видео и voiceover."),
                    ("Runway", "https://runwayml.com/", "AI-видео, генеративный монтаж и creative tools."),
                    ("Synthesia", "https://www.synthesia.io/", "AI video platform с аватарами для обучающих роликов."),
                    ("Canva", "https://www.canva.com/", "Дизайн, презентации и видео-шаблоны для авторов."),
                    ("Pika", "https://pika.art/", "Генерация коротких AI-видео и визуальных сцен."),
                    ("CapCut", "https://www.capcut.com/", "Популярный редактор видео и шаблоны для creator workflow."),
                    ("ElevenLabs", "https://elevenlabs.io/", "AI-голоса, дубляж и voiceover для видео."),
                    ("Descript", "https://www.descript.com/", "Монтаж видео и аудио через текстовый workflow."),
                ]
            )

        if any(keyword in text for keyword in ["notion", "ноушн", "документ", "база знаний"]):
            curated.extend(
                [
                    ("Notion", "https://www.notion.so/product/ai", "AI-функции в рабочем пространстве Notion."),
                    ("Notion Help Center", "https://www.notion.so/help", "Официальная документация и объяснения функций."),
                ]
            )

        if any(keyword in text for keyword in ["автоматиза", "automation", "zapier", "make", "workflow"]):
            curated.extend(
                [
                    ("Make", "https://www.make.com/", "Платформа no-code автоматизации процессов."),
                    ("Zapier", "https://zapier.com/", "Автоматизация приложений и workflows."),
                    ("Airtable", "https://www.airtable.com/", "Базы данных, workflows и операционные системы команд."),
                ]
            )

        if any(keyword in text for keyword in ["youtube", "ютуб", "канал", "creator"]):
            curated.extend(
                [
                    ("YouTube Help", "https://support.google.com/youtube/", "Официальная справка YouTube для авторов."),
                    ("YouTube Creators", "https://www.youtube.com/creators/", "Официальный раздел для авторов YouTube."),
                    ("YouTube Studio", "https://studio.youtube.com/", "Официальная платформа управления каналом и аналитикой."),
                ]
            )

        if any(keyword in text for keyword in ["seo", "сео", "поиск", "ключев", "ranking", "ранжирован"]):
            curated.extend(
                [
                    ("Google Search Central", "https://developers.google.com/search", "Официальная документация Google Search для SEO."),
                    ("Google Trends", "https://trends.google.com/", "Проверка динамики спроса и тем для контента."),
                    ("Ahrefs", "https://ahrefs.com/", "SEO-инструменты для анализа ключей, конкурентов и ссылок."),
                    ("Semrush", "https://www.semrush.com/", "SEO/маркетинговая платформа для keyword research и аудита."),
                    ("Surfer SEO", "https://surferseo.com/", "Контент-оптимизация и SEO workflow для авторов."),
                ]
            )

        if not curated:
            slug = project.topic.strip().split()[0].lower().strip(".,!?;:") or "topic"
            curated.append(
                (
                    "AI-generated research slide",
                    f"https://example.com/research/{slug}",
                    "Fallback-источник: нет curated official website для темы, используем AI-слайд.",
                )
            )

        return [
            SourceCandidate(name=name, url=url, kind=SourceKind.official_website, reason=reason)
            for name, url, reason in curated
        ]

    def _dedupe_sources(self, sources: list[SourceCandidate]) -> list[SourceCandidate]:
        result: list[SourceCandidate] = []
        seen: set[str] = set()
        for source in sources:
            key = self._canonical_url(source.url)
            if key in seen:
                continue
            seen.add(key)
            result.append(source)
        return result

    def _assign_sources_to_scenes(self, project: Project) -> None:
        if not project.sources:
            return
        usage_count: dict[str, int] = {}
        for scene in project.scenes:
            if scene.visual_type not in SOURCE_VISUAL_TYPES:
                continue
            if scene.source_id:
                existing = next((item for item in project.sources if item.id == scene.source_id), None)
                if existing:
                    scene.source_name = existing.name
                    scene.source_url = existing.url
                    usage_count[existing.id] = usage_count.get(existing.id, 0) + 1
                    continue
            source = self._best_source_for_scene(project.sources, scene, usage_count)
            scene.source_id = source.id
            scene.source_name = source.name
            scene.source_url = source.url
            usage_count[source.id] = usage_count.get(source.id, 0) + 1

    def _best_source_for_scene(
        self,
        sources: list[SourceCandidate],
        scene,
        usage_count: dict[str, int],
    ) -> SourceCandidate:
        query_words = self._keywords(" ".join([scene.source_query or "", scene.title, scene.goal, scene.visual_prompt or ""]))
        scored: list[tuple[int, SourceCandidate]] = []
        for source in sources:
            source_words = self._keywords(" ".join([source.name, source.url, source.reason, source.kind.value]))
            overlap = len(query_words.intersection(source_words))
            official_bonus = 3 if source.kind in {SourceKind.official_website, SourceKind.user_provided} else 0
            captured_bonus = 2 if source.status in {"captured", "fallback_card"} and source.screenshot_path else 0
            reuse_penalty = usage_count.get(source.id, 0) * 4
            score = overlap + official_bonus + captured_bonus - reuse_penalty
            scored.append((score, source))
        scored.sort(key=lambda item: (item[0], -usage_count.get(item[1].id, 0), item[1].name.lower()), reverse=True)
        return scored[0][1]

    def _search_queries(self, project: Project) -> list[str]:
        queries = [project.topic]
        for scene in project.scenes:
            if scene.source_query:
                queries.append(scene.source_query)
        result: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = " ".join(query.split())
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            result.append(normalized)
            if len(result) >= 4:
                break
        return result

    def _keywords(self, value: str) -> set[str]:
        tokens = []
        for token in value.lower().replace("https://", " ").replace("http://", " ").split():
            cleaned = token.strip(".,:;!?/()[]{}|\"'«»").replace("www.", "")
            if len(cleaned) < 3:
                continue
            if cleaned in {"official", "website", "features", "pricing", "dashboard", "источник", "сайт"}:
                continue
            tokens.append(cleaned)
        return set(tokens)

    def _write_visual_plan(self, project: Project, project_dir: Path, plan: list[VisualPlanDecision]) -> Path:
        plan_path = ensure_dir(project_dir / "assets") / "visual_plan.json"
        scenes_by_id = {scene.id: scene for scene in project.scenes}
        write_json(
            plan_path,
            [
                {
                    "scene_id": item.scene_id,
                    "scene_order": item.scene_order,
                    "visual_type": item.visual_type,
                    "avatar_visible": item.avatar_visible,
                    "source_query": item.source_query,
                    "source_id": scenes_by_id[item.scene_id].source_id if item.scene_id in scenes_by_id else None,
                    "source_name": scenes_by_id[item.scene_id].source_name if item.scene_id in scenes_by_id else None,
                    "source_url": scenes_by_id[item.scene_id].source_url if item.scene_id in scenes_by_id else None,
                    "visual_prompt": item.visual_prompt,
                    "reason": item.reason,
                }
                for item in plan
            ],
        )
        return plan_path

    def _name_from_url(self, url: str) -> str:
        domain = urlparse(url).netloc or url
        domain = domain.replace("www.", "")
        name = domain.split(".")[0].replace("-", " ").replace("_", " ").strip()
        return name.title() or "User source"

    def _canonical_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.netloc or parsed.path).lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        return f"{host}{path}" if host else url.lower().rstrip("/")
