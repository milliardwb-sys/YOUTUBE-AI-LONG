from __future__ import annotations

from pathlib import Path
from threading import Lock

from app.config import Settings
from app.models import ConsentCreate, ConsentRecord, ConsentType
from app.utils.files import ensure_dir, read_json, write_json
from app.utils.security import validate_consent_id


class ConsentNotFoundError(KeyError):
    pass


class ConsentService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.consents_dir = ensure_dir(settings.data_dir / "_consents")
        self._lock = Lock()

    def record(
        self,
        payload: ConsentCreate,
        *,
        actor_id: str | None = None,
        organization_id: str | None = None,
        project_id: str | None = None,
        request_id: str | None = None,
    ) -> ConsentRecord:
        record = ConsentRecord(
            consent_type=payload.consent_type,
            actor_id=actor_id,
            organization_id=organization_id or payload.organization_id,
            project_id=project_id or payload.project_id,
            voice_id=payload.voice_id,
            granted=payload.granted,
            policy_version=payload.policy_version,
            statement=payload.statement,
            request_id=request_id,
        )
        self.save(record)
        return record

    def save(self, record: ConsentRecord) -> None:
        with self._lock:
            write_json(self.consent_file(record.id), record.model_dump(mode="json"))

    def get(self, consent_id: str) -> ConsentRecord:
        path = self.consent_file(consent_id)
        if not path.exists():
            raise ConsentNotFoundError(consent_id)
        return ConsentRecord.model_validate(read_json(path))

    def list_records(
        self,
        *,
        actor_id: str | None = None,
        organization_id: str | None = None,
        project_id: str | None = None,
        consent_type: ConsentType | None = None,
    ) -> list[ConsentRecord]:
        records: list[ConsentRecord] = []
        for path in sorted(self.consents_dir.glob("consent_*.json")):
            try:
                record = ConsentRecord.model_validate(read_json(path))
            except Exception:
                continue
            if actor_id is not None and record.actor_id != actor_id:
                continue
            if organization_id is not None and record.organization_id != organization_id:
                continue
            if project_id is not None and record.project_id != project_id:
                continue
            if consent_type is not None and record.consent_type != consent_type:
                continue
            records.append(record)
        return sorted(records, key=lambda item: (item.created_at, item.id), reverse=True)

    def has_grant(
        self,
        *,
        consent_type: ConsentType,
        actor_id: str | None = None,
        organization_id: str | None = None,
        project_id: str | None = None,
        voice_id: str | None = None,
    ) -> bool:
        applicable = [
            record
            for record in self.list_records(consent_type=consent_type)
            if self._applies(
                record,
                actor_id=actor_id,
                organization_id=organization_id,
                project_id=project_id,
                voice_id=voice_id,
            )
        ]
        if not applicable:
            return False
        return applicable[0].granted

    def consent_file(self, consent_id: str) -> Path:
        validate_consent_id(consent_id)
        return self.consents_dir / f"{consent_id}.json"

    def _applies(
        self,
        record: ConsentRecord,
        *,
        actor_id: str | None,
        organization_id: str | None,
        project_id: str | None,
        voice_id: str | None,
    ) -> bool:
        if voice_id and record.voice_id and record.voice_id != voice_id:
            return False
        if project_id and record.project_id == project_id:
            return True
        if organization_id and record.organization_id == organization_id and record.project_id is None:
            return True
        return bool(actor_id and record.actor_id == actor_id and record.organization_id is None and record.project_id is None)
