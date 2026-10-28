"""Core schema and tenant policies. Frozen migration; independent of future ORM models."""

from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        '\nCREATE TABLE rate_limits (\n\tkey VARCHAR(64) NOT NULL, \n\t"window" TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcount INTEGER NOT NULL, \n\tPRIMARY KEY (key)\n)\n\n'
    )
    op.execute(
        "\nCREATE TABLE users (\n\temail VARCHAR(320) NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (status IN ('active','disabled')), \n\tCHECK (email = lower(email)), \n\tUNIQUE (email)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE auth_sessions (\n\tuser_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tcsrf VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (token_hash)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at)")
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)")
    op.execute(
        "\nCREATE TABLE institutions (\n\tname VARCHAR(160) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (status IN ('active','suspended')), \n\tFOREIGN KEY(created_by) REFERENCES users (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE platform_admins (\n\tuser_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE recoveries (\n\tuser_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tused_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (token_hash)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_recoveries_user_id ON recoveries (user_id)")
    op.execute(
        "\nCREATE TABLE audit_events (\n\tinstitution_id UUID, \n\tactor_id UUID, \n\taction VARCHAR(80) NOT NULL, \n\ttarget VARCHAR(120) NOT NULL, \n\trequest_id VARCHAR(36) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(institution_id) REFERENCES institutions (id), \n\tFOREIGN KEY(actor_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_audit_tenant_created ON audit_events (institution_id, created_at)")
    op.execute(
        "\nCREATE TABLE data_sources (\n\tname VARCHAR(160) NOT NULL, \n\tcategory VARCHAR(30) NOT NULL, \n\tdescription TEXT NOT NULL, \n\treference VARCHAR(500) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tinstitution_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (institution_id, id), \n\tCHECK (category IN ('google_drive','database','api','file_storage','local_file')), \n\tCHECK (status = 'not_configured'), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(institution_id) REFERENCES institutions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_data_sources_institution_id ON data_sources (institution_id)")
    op.execute(
        "\nCREATE TABLE institution_settings (\n\tdescription TEXT NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tinstitution_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (institution_id), \n\tFOREIGN KEY(institution_id) REFERENCES institutions (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_institution_settings_institution_id ON institution_settings (institution_id)"
    )
    op.execute(
        "\nCREATE TABLE invitations (\n\temail VARCHAR(320) NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\taccepted_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tinvited_by UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tinstitution_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (role IN ('owner','administrator','analyst','viewer')), \n\tUNIQUE (token_hash), \n\tFOREIGN KEY(invited_by) REFERENCES users (id), \n\tFOREIGN KEY(institution_id) REFERENCES institutions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_invitations_institution_id ON invitations (institution_id)")
    op.execute(
        "\nCREATE TABLE memberships (\n\tuser_id UUID NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tinstitution_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (institution_id, user_id), \n\tCHECK (role IN ('owner','administrator','analyst','viewer')), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(institution_id) REFERENCES institutions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_memberships_institution_id ON memberships (institution_id)")
    op.execute("CREATE INDEX ix_memberships_user_id ON memberships (user_id)")
    op.execute(
        "\nCREATE TABLE datasets (\n\tname VARCHAR(160) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tsource_category VARCHAR(30) NOT NULL, \n\tfile_type VARCHAR(80) NOT NULL, \n\tclassification VARCHAR(30) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\ttags JSONB NOT NULL, \n\trecord_count BIGINT, \n\tstorage_bytes BIGINT, \n\tsource_reference VARCHAR(500) NOT NULL, \n\towner_id UUID NOT NULL, \n\tsource_id UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tinstitution_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(institution_id, source_id) REFERENCES data_sources (institution_id, id), \n\tCHECK (record_count >= 0), \n\tCHECK (storage_bytes >= 0), \n\tCHECK (classification IN ('public','internal','confidential','restricted')), \n\tCHECK (status IN ('draft','registered','archived')), \n\tCHECK (source_category IN ('google_drive','database','api','file_storage','local_file')), \n\tFOREIGN KEY(owner_id) REFERENCES users (id), \n\tFOREIGN KEY(institution_id) REFERENCES institutions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_dataset_tenant_status ON datasets (institution_id, status)")
    op.execute("CREATE INDEX ix_datasets_institution_id ON datasets (institution_id)")
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON memberships FOR ALL USING (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid) WITH CHECK (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid)"
    )
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invitations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON invitations FOR ALL USING (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid) WITH CHECK (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid)"
    )
    op.execute("ALTER TABLE institution_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE institution_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON institution_settings FOR ALL USING (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid) WITH CHECK (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid)"
    )
    op.execute("ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE data_sources FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON data_sources FOR ALL USING (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid) WITH CHECK (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid)"
    )
    op.execute("ALTER TABLE datasets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE datasets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON datasets FOR ALL USING (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid) WITH CHECK (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid)"
    )
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY own_membership ON memberships FOR SELECT USING (user_id = nullif(current_setting('pluto.user', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY invitation_token ON invitations FOR SELECT USING (token_hash = current_setting('pluto.invitation', true))"
    )
    op.execute(
        "CREATE POLICY audit_read ON audit_events FOR SELECT USING (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid OR (institution_id IS NULL AND current_setting('pluto.platform', true) = 'true'))"
    )
    op.execute(
        "CREATE POLICY audit_insert ON audit_events FOR INSERT WITH CHECK (institution_id = nullif(current_setting('pluto.tenant', true), '')::uuid OR institution_id IS NULL)"
    )
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO pluto_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pluto_app")
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM pluto_app")


def downgrade():
    op.drop_table("datasets")
    op.drop_table("memberships")
    op.drop_table("invitations")
    op.drop_table("institution_settings")
    op.drop_table("data_sources")
    op.drop_table("audit_events")
    op.drop_table("recoveries")
    op.drop_table("platform_admins")
    op.drop_table("institutions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
    op.drop_table("rate_limits")
