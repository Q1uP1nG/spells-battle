from config import SPELLS


class SimplePVEAI:
    """Minimal AI opponent for PVE mode.  Announces spells before release."""

    def __init__(self, decision_interval=2.5, attack_interval=1.8, cast_windup=1.6):
        self.next_decision_time = 0.0
        self.decision_interval = decision_interval
        self.attack_interval = attack_interval
        self.cast_windup = cast_windup
        self.pending_spell = None
        self.pending_cast_at = 0.0
        self.pending_started_at = 0.0
        self._attack_rotation = ["incendio", "stupefy", "glacius"]
        self._rotation_index = 0
        self._last_protego_time = 0.0
        self._protego_cooldown = 8.0  # internal throttle beyond spell CD

    def update(self, game, now):
        """Possibly cast a spell for P2. Returns spell name or None."""
        player = game.players[1]

        if not player.alive():
            self._clear_pending()
            return None
        if game.winner is not None:
            self._clear_pending()
            return None

        if self.pending_spell is not None:
            return self._release_pending_spell(game, player, now)

        if now < self.next_decision_time:
            return None

        spell_name = self._choose_spell(game, player, now)
        if spell_name is None:
            return None

        self._start_pending_spell(player, spell_name, now)
        return None

    def _start_pending_spell(self, player, spell_name, now):
        self.pending_spell = spell_name
        self.pending_started_at = now
        self.pending_cast_at = now + self.cast_windup
        label = SPELLS[spell_name]["label"]
        player.last_message = f"AI CASTING {label}"
        player.message_until = self.pending_cast_at + 0.2
        player.set_visual_state("casting", now, self.cast_windup + 0.1)

    def _release_pending_spell(self, game, player, now):
        spell_name = self.pending_spell
        allowed, _ = game.can_cast(1, spell_name, now)
        if not allowed:
            self._clear_pending()
            self.next_decision_time = now + 0.5
            return None

        if now < self.pending_cast_at:
            label = SPELLS[spell_name]["label"]
            player.last_message = f"AI CASTING {label}"
            player.message_until = self.pending_cast_at + 0.2
            return None

        did_cast = game.cast_spell(1, spell_name, now)
        self._clear_pending()
        if did_cast:
            self.next_decision_time = now + self.attack_interval
            if spell_name == "protego":
                self._last_protego_time = now
            return spell_name
        else:
            self.next_decision_time = now + 0.5
            return None

    def _choose_spell(self, game, player, now):
        # Priority 1: Heal if HP is low
        hp_ratio = player.hp / max(player.max_hp, 1.0)
        if hp_ratio < 0.35:
            allowed, _ = game.can_cast(1, "lumos", now)
            if allowed:
                return "lumos"

        # Priority 2: Shield if incoming projectiles
        incoming = sum(1 for p in game.projectiles if p.active and p.owner == 0)
        if incoming > 0 and (now - self._last_protego_time) > self._protego_cooldown:
            allowed, _ = game.can_cast(1, "protego", now)
            if allowed:
                return "protego"

        # Priority 3: Attack rotation
        for _ in range(len(self._attack_rotation)):
            spell_name = self._attack_rotation[self._rotation_index % len(self._attack_rotation)]
            self._rotation_index += 1
            allowed, _ = game.can_cast(1, spell_name, now)
            if allowed:
                return spell_name

        # Priority 4: Protego fallback
        allowed, _ = game.can_cast(1, "protego", now)
        if allowed:
            return "protego"

        return None

    def _clear_pending(self):
        self.pending_spell = None
        self.pending_cast_at = 0.0
        self.pending_started_at = 0.0

    def reset(self):
        self.next_decision_time = 0.0
        self._rotation_index = 0
        self._last_protego_time = 0.0
        self._clear_pending()
