"""
Contact management tool — add, list, update, remove contacts from soul/CONTACTS.md.

The contact book is stored as a markdown file with structured entries.
Each contact has: name, relation type, optional details, and date added.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ContactTool:
    """Manage owner's personal contacts in soul/CONTACTS.md.

    Actions:
    - add: create a new contact entry
    - list: show all contacts
    - remove: delete a contact by name
    - update: modify existing contact details
    """

    def __init__(self, contacts_path: str | Path = "soul/CONTACTS.md") -> None:
        self._path = Path(contacts_path).resolve()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="contact",
            description=(
                "Manage owner's contacts. Add new contacts, list existing ones, "
                "update contact information, or remove contacts from the contact book. "
                "Each contact has a name, relation type (home/friend/colleague/partner/family/other), "
                "and optional details."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action to perform",
                    required=True,
                    enum=["add", "list", "remove", "update"],
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="Contact name (required for add/remove/update)",
                    required=False,
                ),
                ToolParameter(
                    name="relation",
                    type="string",
                    description=(
                        "Relationship type: home, friend, colleague, partner, family, other "
                        "(for add/update)"
                    ),
                    required=False,
                    enum=["home", "friend", "colleague", "partner", "family", "other"],
                ),
                ToolParameter(
                    name="details",
                    type="string",
                    description="Optional notes about the contact (for add/update)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs.get("action", "").lower()
        name: str | None = kwargs.get("name")
        relation: str | None = kwargs.get("relation")
        details: str | None = kwargs.get("details")

        if action not in ("add", "list", "remove", "update"):
            return ToolResult(
                success=False,
                error=f"Invalid action: {action}. Must be: add, list, remove, update",
            )

        if action == "list":
            return await self._list_contacts()
        elif action == "add":
            if not name:
                return ToolResult(success=False, error="name is required for add")
            if not relation:
                return ToolResult(success=False, error="relation is required for add")
            return await self._add_contact(name, relation, details)
        elif action == "remove":
            if not name:
                return ToolResult(success=False, error="name is required for remove")
            return await self._remove_contact(name)
        elif action == "update":
            if not name:
                return ToolResult(success=False, error="name is required for update")
            return await self._update_contact(name, relation, details)

        return ToolResult(success=False, error="Unknown action")

    async def _list_contacts(self) -> ToolResult:
        """List all contacts from the file."""
        if not self._path.exists():
            return ToolResult(
                success=True,
                data="No contacts yet. Use action='add' to create the first contact.",
            )

        content = self._path.read_text(encoding="utf-8")
        contacts = self._parse_contacts(content)

        if not contacts:
            return ToolResult(
                success=True,
                data="No contacts in the contact book yet.",
            )

        # Format as readable list
        lines = [f"Contacts ({len(contacts)} total):\n"]
        for contact in contacts:
            lines.append(
                f"• {contact['name']} ({contact['relation']})"
            )
            if contact.get("details"):
                lines.append(f"  {contact['details']}")
            if contact.get("added"):
                lines.append(f"  Added: {contact['added']}")
            lines.append("")

        return ToolResult(success=True, data="\n".join(lines))

    async def _add_contact(
        self, name: str, relation: str, details: str | None
    ) -> ToolResult:
        """Add a new contact to the file."""
        # Ensure file exists
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Create initial file with header
            self._path.write_text(
                "# Contacts\n\n"
                "Owner's personal and professional contacts. Managed dynamically by the agent.\n\n"
                "## Format\n"
                "Each contact entry:\n"
                "```\n"
                "### [Name]\n"
                "- **Relation:** [home/friend/colleague/partner/family/other]\n"
                "- **Details:** [optional notes about the person]\n"
                "- **Added:** [YYYY-MM-DD]\n"
                "```\n\n"
                "---\n\n",
                encoding="utf-8",
            )

        content = self._path.read_text(encoding="utf-8")
        contacts = self._parse_contacts(content)

        # Check if contact already exists
        if any(c["name"].lower() == name.lower() for c in contacts):
            return ToolResult(
                success=False,
                error=f"Contact '{name}' already exists. Use action='update' to modify.",
            )

        # Build new contact entry
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = f"### {name}\n"
        entry += f"- **Relation:** {relation}\n"
        if details:
            entry += f"- **Details:** {details}\n"
        entry += f"- **Added:** {today}\n\n"

        # Find the position to insert (after the header section and ---)
        # Remove the placeholder text if it exists
        content = re.sub(
            r"\*No contacts yet\. Use contact tools to add people here\.\*\s*",
            "",
            content,
        )

        # Append to the end
        if not content.endswith("\n\n"):
            content = content.rstrip() + "\n\n"
        content += entry

        self._path.write_text(content, encoding="utf-8")
        logger.info("Contact added: %s (%s)", name, relation)

        return ToolResult(
            success=True,
            data=f"Added contact: {name} ({relation})\nAdded: {today}",
        )

    async def _remove_contact(self, name: str) -> ToolResult:
        """Remove a contact from the file."""
        if not self._path.exists():
            return ToolResult(success=False, error="No contacts file found")

        content = self._path.read_text(encoding="utf-8")
        contacts = self._parse_contacts(content)

        # Find contact
        found = None
        for contact in contacts:
            if contact["name"].lower() == name.lower():
                found = contact
                break

        if not found:
            return ToolResult(success=False, error=f"Contact '{name}' not found")

        # Remove the contact section from the file
        # Pattern: ### Name\n followed by bullet points until next ### or end
        pattern = rf"### {re.escape(found['name'])}\n(- \*\*.*?\n)+\n?"
        new_content = re.sub(pattern, "", content, flags=re.MULTILINE)

        # If no contacts left, add placeholder
        remaining = self._parse_contacts(new_content)
        if not remaining:
            # Find position after "---" separator
            if "---\n\n" in new_content:
                new_content = new_content.replace(
                    "---\n\n",
                    "---\n\n*No contacts yet. Use contact tools to add people here.*\n",
                )

        self._path.write_text(new_content, encoding="utf-8")
        logger.info("Contact removed: %s", name)

        return ToolResult(
            success=True,
            data=f"Removed contact: {found['name']} ({found['relation']})",
        )

    async def _update_contact(
        self, name: str, relation: str | None, details: str | None
    ) -> ToolResult:
        """Update an existing contact."""
        if not self._path.exists():
            return ToolResult(success=False, error="No contacts file found")

        content = self._path.read_text(encoding="utf-8")
        contacts = self._parse_contacts(content)

        # Find contact
        found = None
        for contact in contacts:
            if contact["name"].lower() == name.lower():
                found = contact
                break

        if not found:
            return ToolResult(success=False, error=f"Contact '{name}' not found")

        # Build updated entry
        updated_relation = relation if relation else found.get("relation", "other")
        updated_details = details if details is not None else found.get("details")

        new_entry = f"### {found['name']}\n"
        new_entry += f"- **Relation:** {updated_relation}\n"
        if updated_details:
            new_entry += f"- **Details:** {updated_details}\n"
        new_entry += f"- **Added:** {found.get('added', 'unknown')}\n\n"

        # Replace old entry
        pattern = rf"### {re.escape(found['name'])}\n(- \*\*.*?\n)+\n?"
        new_content = re.sub(
            pattern, new_entry, content, count=1, flags=re.MULTILINE
        )

        self._path.write_text(new_content, encoding="utf-8")
        logger.info("Contact updated: %s", name)

        return ToolResult(
            success=True,
            data=f"Updated contact: {found['name']}\nRelation: {updated_relation}"
            + (f"\nDetails: {updated_details}" if updated_details else ""),
        )

    @staticmethod
    def _parse_contacts(content: str) -> list[dict[str, str]]:
        """Parse markdown content into contact dicts.

        Returns list of dicts with keys: name, relation, details, added.
        """
        contacts: list[dict[str, str]] = []

        # Find all ### headers followed by bullet points
        # Pattern: ### Name\n- **Relation:** ...\n- **Details:** ...\n- **Added:** ...
        pattern = r"### (.+?)\n((?:- \*\*.*?\n)+)"
        matches = re.finditer(pattern, content, re.MULTILINE)

        for match in matches:
            name = match.group(1).strip()
            fields_block = match.group(2)

            contact: dict[str, str] = {"name": name}

            # Parse fields
            relation_match = re.search(
                r"- \*\*Relation:\*\* (.+)", fields_block
            )
            if relation_match:
                contact["relation"] = relation_match.group(1).strip()

            details_match = re.search(r"- \*\*Details:\*\* (.+)", fields_block)
            if details_match:
                contact["details"] = details_match.group(1).strip()

            added_match = re.search(r"- \*\*Added:\*\* (.+)", fields_block)
            if added_match:
                contact["added"] = added_match.group(1).strip()

            contacts.append(contact)

        return contacts
