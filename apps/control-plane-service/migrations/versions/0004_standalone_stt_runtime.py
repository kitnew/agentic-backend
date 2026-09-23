"""Move Realtime STT configuration to the standalone system default.

Revision ID: 0004_standalone_stt_runtime
Revises: 0003_half_cascade_architecture
"""

from alembic import op

revision = "0004_standalone_stt_runtime"
down_revision = "0003_half_cascade_architecture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE control_plane.live_components
        SET value = value - 'input_transcription'
        WHERE kind = 'RealtimeDefaults'
          AND value ? 'input_transcription'
        """
    )


def downgrade() -> None:
    # The former STT ref may differ from STTDefaults and cannot be reconstructed.
    pass
