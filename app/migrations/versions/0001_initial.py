"""Initial PostgreSQL schema (frozen; independent of application models)."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE audit_events (
    id VARCHAR(36) NOT NULL, 
    project_id VARCHAR(36) NOT NULL, 
    action VARCHAR(100) NOT NULL, 
    resource_id VARCHAR(36) NOT NULL, 
    details JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
)""")
    op.execute(
        """CREATE INDEX ix_audit_events_project_id ON audit_events (project_id)"""
    )
    op.execute("""CREATE TABLE projects (
    id VARCHAR(36) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    owner_actor VARCHAR(200) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
)""")
    op.execute("""CREATE INDEX ix_projects_owner_actor ON projects (owner_actor)""")
    op.execute("""CREATE TABLE targets (
    id VARCHAR(36) NOT NULL, 
    project_id VARCHAR(36) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    image VARCHAR(300) NOT NULL, 
    url VARCHAR(500) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(project_id) REFERENCES projects (id)
)""")
    op.execute("""CREATE INDEX ix_targets_project_id ON targets (project_id)""")
    op.execute("""CREATE TABLE authorization_scopes (
    id VARCHAR(36) NOT NULL, 
    project_id VARCHAR(36) NOT NULL, 
    target_id VARCHAR(36) NOT NULL, 
    allowed_url VARCHAR(500) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(project_id) REFERENCES projects (id), 
    FOREIGN KEY(target_id) REFERENCES targets (id)
)""")
    op.execute(
        """CREATE INDEX ix_authorization_scopes_project_id ON authorization_scopes (project_id)"""
    )
    op.execute("""CREATE TABLE assessments (
    id VARCHAR(36) NOT NULL, 
    project_id VARCHAR(36) NOT NULL, 
    target_id VARCHAR(36) NOT NULL, 
    scope_id VARCHAR(36) NOT NULL, 
    profile VARCHAR(50) NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    result JSON, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(project_id) REFERENCES projects (id), 
    FOREIGN KEY(target_id) REFERENCES targets (id), 
    FOREIGN KEY(scope_id) REFERENCES authorization_scopes (id)
)""")
    op.execute("""CREATE INDEX ix_assessments_project_id ON assessments (project_id)""")
    op.execute("""CREATE TABLE evidence (
    id VARCHAR(36) NOT NULL, 
    assessment_id VARCHAR(36) NOT NULL, 
    kind VARCHAR(100) NOT NULL, 
    data JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(assessment_id) REFERENCES assessments (id)
)""")
    op.execute("""CREATE INDEX ix_evidence_assessment_id ON evidence (assessment_id)""")
    op.execute("""CREATE TABLE findings (
    id VARCHAR(36) NOT NULL, 
    assessment_id VARCHAR(36) NOT NULL, 
    plugin VARCHAR(100) NOT NULL, 
    title VARCHAR(300) NOT NULL, 
    severity VARCHAR(30) NOT NULL, 
    description TEXT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(assessment_id) REFERENCES assessments (id)
)""")
    op.execute("""CREATE INDEX ix_findings_assessment_id ON findings (assessment_id)""")


def downgrade():
    op.drop_table("findings")
    op.drop_table("evidence")
    op.drop_table("assessments")
    op.drop_table("authorization_scopes")
    op.drop_table("targets")
    op.drop_table("projects")
    op.drop_table("audit_events")
