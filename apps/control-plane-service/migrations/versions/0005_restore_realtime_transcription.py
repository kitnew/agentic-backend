"""Restore the Realtime transcription reference removed by revision 0004.

Revision ID: 0005_restore_realtime_transcription
Revises: 0004_standalone_stt_runtime
"""

from alembic import op

revision = "0005_restore_realtime_transcription"
down_revision = "0004_standalone_stt_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0004 discarded the explicit reference. Recover only an unambiguous
    # transcription deployment on the Realtime model's Azure connection.
    # Abort otherwise so an operator can restore the intended ref explicitly.
    op.execute(
        """
        DO $$
        DECLARE candidate uuid;
        DECLARE candidate_count integer;
        BEGIN
          IF EXISTS (
            SELECT 1 FROM control_plane.live_components
            WHERE kind = 'RealtimeDefaults' AND NOT value ? 'input_transcription'
          ) THEN
          SELECT count(*), (array_agg(stt.id))[1] INTO candidate_count, candidate
          FROM control_plane.live_components AS live
          JOIN control_plane.model_deployments AS model
            ON model.id = (live.value ->> 'deployment_ref')::uuid
          JOIN control_plane.model_deployments AS stt
            ON stt.connection_id = model.connection_id
           AND stt.deployment_kind = 'stt'
           AND COALESCE(stt.capabilities ->> 'supports_realtime_input_transcription', 'false') = 'true'
          WHERE live.kind = 'RealtimeDefaults'
            AND NOT live.value ? 'input_transcription';
          IF candidate_count != 1 THEN
            RAISE EXCEPTION 'Cannot restore Realtime input_transcription: expected one eligible STT deployment on its model connection, found %', candidate_count;
          END IF;
          UPDATE control_plane.live_components
          SET value = jsonb_set(value, '{input_transcription}', jsonb_build_object('deployment_ref', candidate::text))
          WHERE kind = 'RealtimeDefaults' AND NOT value ? 'input_transcription';
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    pass
