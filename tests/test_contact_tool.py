"""Tests for contact management tool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.tools.contact_tool import ContactTool


@pytest.fixture
def temp_contacts_file():
    """Create a temporary contacts file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(
            "# Contacts\n\n"
            "Owner's personal and professional contacts.\n\n"
            "---\n\n"
            "*No contacts yet. Use contact tools to add people here.*\n"
        )
        path = Path(f.name)
    yield path
    # Cleanup
    if path.exists():
        path.unlink()


@pytest.mark.asyncio
async def test_add_contact(temp_contacts_file):
    """Test adding a new contact."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    result = await tool.execute(
        action="add",
        name="John Doe",
        relation="friend",
        details="Met at conference",
    )

    assert result.success
    assert "John Doe" in result.data
    assert "friend" in result.data

    # Verify file was written
    content = temp_contacts_file.read_text(encoding="utf-8")
    assert "### John Doe" in content
    assert "**Relation:** friend" in content
    assert "**Details:** Met at conference" in content


@pytest.mark.asyncio
async def test_list_empty_contacts(temp_contacts_file):
    """Test listing when no contacts exist."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    result = await tool.execute(action="list")

    assert result.success
    assert "No contacts" in result.data


@pytest.mark.asyncio
async def test_list_contacts(temp_contacts_file):
    """Test listing contacts after adding some."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    # Add two contacts
    await tool.execute(
        action="add", name="Alice", relation="colleague", details="Software engineer"
    )
    await tool.execute(action="add", name="Bob", relation="family")

    result = await tool.execute(action="list")

    assert result.success
    assert "Alice" in result.data
    assert "colleague" in result.data
    assert "Bob" in result.data
    assert "family" in result.data


@pytest.mark.asyncio
async def test_remove_contact(temp_contacts_file):
    """Test removing a contact."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    # Add and then remove
    await tool.execute(action="add", name="Charlie", relation="partner")

    result = await tool.execute(action="remove", name="Charlie")

    assert result.success
    assert "Charlie" in result.data

    # Verify removed from file
    content = temp_contacts_file.read_text(encoding="utf-8")
    assert "### Charlie" not in content


@pytest.mark.asyncio
async def test_update_contact(temp_contacts_file):
    """Test updating an existing contact."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    # Add contact
    await tool.execute(action="add", name="Diana", relation="friend")

    # Update relation and details
    result = await tool.execute(
        action="update",
        name="Diana",
        relation="colleague",
        details="Now working together",
    )

    assert result.success
    assert "Diana" in result.data

    # Verify changes in file
    content = temp_contacts_file.read_text(encoding="utf-8")
    assert "**Relation:** colleague" in content
    assert "**Details:** Now working together" in content


@pytest.mark.asyncio
async def test_add_duplicate_contact(temp_contacts_file):
    """Test that adding duplicate contact fails."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    # Add first time
    await tool.execute(action="add", name="Eve", relation="friend")

    # Try adding again
    result = await tool.execute(action="add", name="Eve", relation="colleague")

    assert not result.success
    assert "already exists" in result.error


@pytest.mark.asyncio
async def test_remove_nonexistent_contact(temp_contacts_file):
    """Test removing a contact that doesn't exist."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    result = await tool.execute(action="remove", name="Nobody")

    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_update_nonexistent_contact(temp_contacts_file):
    """Test updating a contact that doesn't exist."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    result = await tool.execute(action="update", name="Nobody", relation="friend")

    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_missing_required_fields():
    """Test validation of required parameters."""
    tool = ContactTool()

    # Missing name for add
    result = await tool.execute(action="add", relation="friend")
    assert not result.success

    # Missing relation for add
    result = await tool.execute(action="add", name="Test")
    assert not result.success

    # Missing name for remove
    result = await tool.execute(action="remove")
    assert not result.success


@pytest.mark.asyncio
async def test_contact_case_insensitive_matching(temp_contacts_file):
    """Test that contact names are matched case-insensitively."""
    tool = ContactTool(contacts_path=temp_contacts_file)

    # Add with one case
    await tool.execute(action="add", name="Frank Smith", relation="friend")

    # Remove with different case
    result = await tool.execute(action="remove", name="frank smith")

    assert result.success
