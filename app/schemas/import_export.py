"""Import/export schemas."""

from typing import Literal

from sqlmodel import SQLModel

ImportFormatLiteral = Literal["csv", "jira_csv", "trello_json", "asana_csv"]


class ImportIssue(SQLModel):
    row: int
    message: str


class ImportSummary(SQLModel):
    format: str
    dry_run: bool
    rows: int
    created_tasks: int
    created_labels: int
    skipped: int
    issues: list[ImportIssue]
