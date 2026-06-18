from __future__ import annotations

from pathlib import Path
from threading import Lock

from app.config import Settings
from app.models import Organization, OrganizationCreate, OrganizationMember, OrganizationRole, PlatformUser
from app.utils.files import ensure_dir, read_json, write_json
from app.utils.security import validate_organization_id, validate_user_id


class OrganizationNotFoundError(KeyError):
    pass


class OrganizationMemberNotFoundError(KeyError):
    pass


class LastOrganizationOwnerError(RuntimeError):
    pass


class OrganizationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root_dir = ensure_dir(settings.data_dir / "_organizations")
        self.organizations_dir = ensure_dir(self.root_dir / "organizations")
        self.members_dir = ensure_dir(self.root_dir / "members")
        self._lock = Lock()

    def create(self, payload: OrganizationCreate, owner: PlatformUser) -> Organization:
        with self._lock:
            organization = Organization(name=payload.name, created_by_user_id=owner.id)
            self._save_organization(organization)
            self._save_member(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=owner.id,
                    email=owner.email,
                    role=OrganizationRole.owner,
                )
            )
            return organization

    def ensure_personal_organization(self, user: PlatformUser) -> Organization:
        existing = [
            organization
            for organization in self.list_for_user(user.id)
            if organization.created_by_user_id == user.id and not organization.disabled
        ]
        if existing:
            return sorted(existing, key=lambda item: item.created_at)[0]
        name = f"{user.name or user.email.split('@')[0]}'s workspace"
        return self.create(OrganizationCreate(name=name), user)

    def get(self, organization_id: str) -> Organization:
        path = self.organization_file(organization_id)
        if not path.exists():
            raise OrganizationNotFoundError(organization_id)
        organization = Organization.model_validate(read_json(path))
        if organization.disabled:
            raise OrganizationNotFoundError(organization_id)
        return organization

    def list_for_user(self, user_id: str) -> list[Organization]:
        validate_user_id(user_id)
        organizations: list[Organization] = []
        for member in self.list_members_for_user(user_id):
            try:
                organizations.append(self.get(member.organization_id))
            except OrganizationNotFoundError:
                continue
        return sorted(organizations, key=lambda item: (item.created_at, item.id), reverse=True)

    def list_members_for_user(self, user_id: str) -> list[OrganizationMember]:
        validate_user_id(user_id)
        members: list[OrganizationMember] = []
        for path in sorted(self.members_dir.glob(f"org_*__{user_id}.json")):
            try:
                members.append(OrganizationMember.model_validate(read_json(path)))
            except Exception:
                continue
        return members

    def list_members(self, organization_id: str) -> list[OrganizationMember]:
        validate_organization_id(organization_id)
        members: list[OrganizationMember] = []
        for path in sorted(self.members_dir.glob(f"{organization_id}__user_*.json")):
            try:
                members.append(OrganizationMember.model_validate(read_json(path)))
            except Exception:
                continue
        return sorted(members, key=lambda item: (item.role.value, item.email or item.user_id))

    def member_count(self, organization_id: str) -> int:
        return len(self.list_members(organization_id))

    def get_member(self, organization_id: str, user_id: str) -> OrganizationMember:
        path = self.member_file(organization_id, user_id)
        if not path.exists():
            raise OrganizationMemberNotFoundError(user_id)
        return OrganizationMember.model_validate(read_json(path))

    def role_for_user(self, organization_id: str | None, user_id: str | None) -> OrganizationRole | None:
        if not organization_id or not user_id:
            return None
        try:
            return self.get_member(organization_id, user_id).role
        except OrganizationMemberNotFoundError:
            return None

    def add_member(self, organization_id: str, user: PlatformUser, role: OrganizationRole) -> OrganizationMember:
        self.get(organization_id)
        with self._lock:
            try:
                member = self.get_member(organization_id, user.id)
                member.role = role
                member.email = user.email
                member.touch()
            except OrganizationMemberNotFoundError:
                member = OrganizationMember(
                    organization_id=organization_id,
                    user_id=user.id,
                    email=user.email,
                    role=role,
                )
            self._save_member(member)
            return member

    def update_member_role(self, organization_id: str, user_id: str, role: OrganizationRole) -> OrganizationMember:
        self.get(organization_id)
        with self._lock:
            member = self.get_member(organization_id, user_id)
            if member.role == OrganizationRole.owner and role != OrganizationRole.owner:
                self._raise_if_last_owner(organization_id, user_id)
            member.role = role
            member.touch()
            self._save_member(member)
            return member

    def remove_member(self, organization_id: str, user_id: str) -> None:
        self.get(organization_id)
        with self._lock:
            member = self.get_member(organization_id, user_id)
            if member.role == OrganizationRole.owner:
                self._raise_if_last_owner(organization_id, user_id)
            self.member_file(organization_id, user_id).unlink(missing_ok=True)

    def organization_file(self, organization_id: str) -> Path:
        validate_organization_id(organization_id)
        return self.organizations_dir / f"{organization_id}.json"

    def member_file(self, organization_id: str, user_id: str) -> Path:
        validate_organization_id(organization_id)
        validate_user_id(user_id)
        return self.members_dir / f"{organization_id}__{user_id}.json"

    def _save_organization(self, organization: Organization) -> None:
        organization.touch()
        write_json(self.organization_file(organization.id), organization.model_dump(mode="json"))

    def _save_member(self, member: OrganizationMember) -> None:
        member.touch()
        write_json(self.member_file(member.organization_id, member.user_id), member.model_dump(mode="json"))

    def _raise_if_last_owner(self, organization_id: str, user_id: str) -> None:
        owners = [member for member in self.list_members(organization_id) if member.role == OrganizationRole.owner]
        if len(owners) == 1 and owners[0].user_id == user_id:
            raise LastOrganizationOwnerError("Organization must keep at least one owner")
