"""Shared API assertions for unchanged persistence and assessment requests."""

from sqlalchemy import select


def snapshot(database):
    with database.engine.connect() as connection:
        return {
            table.name: [
                dict(row)
                for row in connection.execute(
                    select(table).order_by(table.c.id)
                ).mappings()
            ]
            for table in database.Base.metadata.sorted_tables
        }


def submission(graph):
    return {
        "project_id": graph.project.id,
        "target_id": graph.target.id,
        "url": graph.assessment.url,
        "plugins": ["security-headers"],
    }
