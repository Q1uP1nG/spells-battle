from __future__ import annotations


class SnapshotInterpolator:
    """Interpolates projectile positions between the latest two server snapshots."""

    def __init__(self):
        self.previous = None
        self.current = None
        self.current_received_at = 0.0

    def push(self, snapshot, received_at):
        if self.current is not None and snapshot.server_tick <= self.current.server_tick:
            return False
        self.previous = self.current
        self.current = snapshot
        self.current_received_at = float(received_at)
        return True

    def projectile_positions(self, now):
        if self.current is None:
            return {}
        current = {projectile.projectile_id: projectile for projectile in self.current.projectiles}
        if self.previous is None:
            return {
                projectile_id: (projectile.x, projectile.y)
                for projectile_id, projectile in current.items()
            }
        previous = {
            projectile.projectile_id: projectile for projectile in self.previous.projectiles
        }
        duration = max(self.current.match_time - self.previous.match_time, 1e-6)
        alpha = min(1.0, max(0.0, (float(now) - self.current_received_at) / duration))
        positions = {}
        for projectile_id, projectile in current.items():
            before = previous.get(projectile_id)
            if before is None:
                positions[projectile_id] = (projectile.x, projectile.y)
            else:
                positions[projectile_id] = (
                    before.x + (projectile.x - before.x) * alpha,
                    before.y + (projectile.y - before.y) * alpha,
                )
        return positions
