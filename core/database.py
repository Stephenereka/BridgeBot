import aiosqlite
import uuid
import json
from config import Config


class Database:
    def __init__(self):
        self.path = Config.DB_PATH
        self._conn = None

    async def init(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self):
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                admin_role_id INTEGER,
                admin_channel_id INTEGER,
                audit_channel_id INTEGER,
                alert_channel_id INTEGER,
                bot_kicked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS federations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner_server_id INTEGER NOT NULL,
                description TEXT,
                invite_only INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS federation_members (
                id TEXT PRIMARY KEY,
                federation_id TEXT NOT NULL,
                server_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                invited_by INTEGER,
                consented_by INTEGER,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(federation_id, server_id)
            );

            CREATE TABLE IF NOT EXISTS channel_bridges (
                id TEXT PRIMARY KEY,
                federation_id TEXT,
                channel_a_id INTEGER NOT NULL,
                channel_a_server_id INTEGER NOT NULL,
                channel_b_id INTEGER NOT NULL,
                channel_b_server_id INTEGER NOT NULL,
                webhook_a_url TEXT,
                webhook_b_url TEXT,
                relay_edits INTEGER DEFAULT 1,
                relay_deletes INTEGER DEFAULT 0,
                relay_attachments INTEGER DEFAULT 1,
                relay_embeds INTEGER DEFAULT 1,
                nsfw_allowed INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                paused INTEGER DEFAULT 0,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_a_id, channel_b_id)
            );

            CREATE TABLE IF NOT EXISTS message_map (
                id TEXT PRIMARY KEY,
                bridge_id TEXT NOT NULL,
                original_message_id INTEGER NOT NULL,
                original_channel_id INTEGER NOT NULL,
                original_server_id INTEGER NOT NULL,
                relayed_message_id INTEGER NOT NULL,
                relayed_channel_id INTEGER NOT NULL,
                relayed_server_id INTEGER NOT NULL,
                relayed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS role_mappings (
                id TEXT PRIMARY KEY,
                federation_id TEXT NOT NULL,
                source_server_id INTEGER NOT NULL,
                source_role_id INTEGER NOT NULL,
                target_server_id INTEGER NOT NULL,
                target_role_id INTEGER NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_server_id, source_role_id, target_server_id)
            );

            CREATE TABLE IF NOT EXISTS ban_relay (
                id TEXT PRIMARY KEY,
                federation_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                banned_in_server INTEGER NOT NULL,
                banned_by INTEGER,
                reason TEXT,
                unbanned_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ban_relay_config (
                id TEXT PRIMARY KEY,
                federation_id TEXT NOT NULL,
                server_id INTEGER NOT NULL,
                enabled INTEGER DEFAULT 0,
                auto_ban INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(federation_id, server_id)
            );

            CREATE TABLE IF NOT EXISTS ban_relay_excluded (
                id TEXT PRIMARY KEY,
                federation_id TEXT NOT NULL,
                server_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                excluded_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(federation_id, server_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                server_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                success INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS server_blacklist (
                id TEXT PRIMARY KEY,
                server_id INTEGER NOT NULL,
                blocked_server_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(server_id, blocked_server_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bridges_ch_a ON channel_bridges(channel_a_id);
            CREATE INDEX IF NOT EXISTS idx_bridges_ch_b ON channel_bridges(channel_b_id);
            CREATE INDEX IF NOT EXISTS idx_msgmap_original ON message_map(original_message_id);
            CREATE INDEX IF NOT EXISTS idx_audit_server ON audit_log(server_id);
        """)
        # Run migrations for columns added after initial deploy
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self):
        """Add columns/tables that may not exist in older DBs."""
        try:
            await self._conn.execute("ALTER TABLE servers ADD COLUMN alert_channel_id INTEGER")
            await self._conn.commit()
        except Exception:
            pass

    # ── Servers ────────────────────────────────────────────────────────────────

    async def upsert_server(self, guild):
        await self._conn.execute("""
            INSERT INTO servers (id, name, owner_id) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, owner_id=excluded.owner_id, bot_kicked=0
        """, (guild.id, guild.name, guild.owner_id))
        await self._conn.commit()

    async def get_server(self, server_id):
        async with self._conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)) as cur:
            return await cur.fetchone()

    async def update_server_config(self, server_id, key, value):
        allowed = {'admin_role_id', 'admin_channel_id', 'audit_channel_id', 'alert_channel_id'}
        if key not in allowed:
            raise ValueError(f"Invalid config key: {key}")
        await self._conn.execute(f"UPDATE servers SET {key} = ? WHERE id = ?", (value, server_id))
        await self._conn.commit()

    async def mark_server_kicked(self, server_id):
        await self._conn.execute("UPDATE servers SET bot_kicked = 1 WHERE id = ?", (server_id,))
        await self._conn.execute(
            "UPDATE channel_bridges SET active = 0 WHERE channel_a_server_id = ? OR channel_b_server_id = ?",
            (server_id, server_id)
        )
        await self._conn.commit()

    async def get_all_active_servers(self):
        async with self._conn.execute("SELECT id FROM servers WHERE bot_kicked = 0") as cur:
            return await cur.fetchall()

    # ── Bridges ────────────────────────────────────────────────────────────────

    async def create_bridge(self, bridge_id, channel_a_id, server_a_id, channel_b_id, server_b_id, created_by, federation_id=None):
        await self._conn.execute("""
            INSERT INTO channel_bridges
            (id, federation_id, channel_a_id, channel_a_server_id, channel_b_id, channel_b_server_id, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (bridge_id, federation_id, channel_a_id, server_a_id, channel_b_id, server_b_id, created_by))
        await self._conn.commit()

    async def get_bridge(self, bridge_id):
        async with self._conn.execute("SELECT * FROM channel_bridges WHERE id = ?", (bridge_id,)) as cur:
            return await cur.fetchone()

    async def get_bridges_for_channel(self, channel_id):
        async with self._conn.execute("""
            SELECT * FROM channel_bridges
            WHERE (channel_a_id = ? OR channel_b_id = ?) AND active = 1 AND paused = 0
        """, (channel_id, channel_id)) as cur:
            return await cur.fetchall()

    async def get_bridges_for_server(self, server_id):
        async with self._conn.execute("""
            SELECT * FROM channel_bridges
            WHERE channel_a_server_id = ? OR channel_b_server_id = ?
        """, (server_id, server_id)) as cur:
            return await cur.fetchall()

    async def get_all_active_bridges(self):
        async with self._conn.execute("SELECT * FROM channel_bridges WHERE active = 1 AND paused = 0") as cur:
            return await cur.fetchall()

    async def delete_bridge(self, bridge_id):
        await self._conn.execute("DELETE FROM channel_bridges WHERE id = ?", (bridge_id,))
        await self._conn.execute("DELETE FROM message_map WHERE bridge_id = ?", (bridge_id,))
        await self._conn.commit()

    async def set_bridge_paused(self, bridge_id, paused):
        await self._conn.execute("UPDATE channel_bridges SET paused = ? WHERE id = ?", (1 if paused else 0, bridge_id))
        await self._conn.commit()

    async def update_bridge_webhooks(self, bridge_id, webhook_a_url=None, webhook_b_url=None):
        if webhook_a_url:
            await self._conn.execute("UPDATE channel_bridges SET webhook_a_url = ? WHERE id = ?", (webhook_a_url, bridge_id))
        if webhook_b_url:
            await self._conn.execute("UPDATE channel_bridges SET webhook_b_url = ? WHERE id = ?", (webhook_b_url, bridge_id))
        await self._conn.commit()

    async def toggle_bridge_setting(self, bridge_id, setting):
        allowed = {'relay_edits', 'relay_deletes', 'relay_attachments', 'relay_embeds', 'nsfw_allowed'}
        if setting not in allowed:
            raise ValueError(f"Invalid setting: {setting}")
        await self._conn.execute(
            f"UPDATE channel_bridges SET {setting} = CASE WHEN {setting} = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (bridge_id,)
        )
        await self._conn.commit()

    async def get_bridge_message_count(self, bridge_id):
        async with self._conn.execute("SELECT COUNT(*) as cnt FROM message_map WHERE bridge_id = ?", (bridge_id,)) as cur:
            row = await cur.fetchone()
            return row['cnt'] if row else 0

    # ── Message Map ────────────────────────────────────────────────────────────

    async def save_message_map(self, map_id, bridge_id, orig_msg_id, orig_ch_id, orig_sv_id, relay_msg_id, relay_ch_id, relay_sv_id):
        await self._conn.execute("""
            INSERT OR IGNORE INTO message_map
            (id, bridge_id, original_message_id, original_channel_id, original_server_id,
             relayed_message_id, relayed_channel_id, relayed_server_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (map_id, bridge_id, orig_msg_id, orig_ch_id, orig_sv_id, relay_msg_id, relay_ch_id, relay_sv_id))
        await self._conn.commit()

    async def get_relayed_messages(self, original_message_id):
        async with self._conn.execute(
            "SELECT * FROM message_map WHERE original_message_id = ?", (original_message_id,)
        ) as cur:
            return await cur.fetchall()

    # ── Federations ────────────────────────────────────────────────────────────

    async def create_federation(self, fed_id, name, owner_server_id, description=None):
        await self._conn.execute("""
            INSERT INTO federations (id, name, owner_server_id, description) VALUES (?, ?, ?, ?)
        """, (fed_id, name, owner_server_id, description))
        await self._conn.execute("""
            INSERT INTO federation_members (id, federation_id, server_id, status) VALUES (?, ?, ?, 'active')
        """, (str(uuid.uuid4()), fed_id, owner_server_id))
        await self._conn.commit()

    async def get_federation(self, fed_id):
        async with self._conn.execute("SELECT * FROM federations WHERE id = ?", (fed_id,)) as cur:
            return await cur.fetchone()

    async def get_federations_for_server(self, server_id):
        async with self._conn.execute("""
            SELECT f.*, fm.status FROM federations f
            JOIN federation_members fm ON f.id = fm.federation_id
            WHERE fm.server_id = ? AND fm.status = 'active'
        """, (server_id,)) as cur:
            return await cur.fetchall()

    async def get_federation_members(self, fed_id):
        async with self._conn.execute("""
            SELECT fm.*, s.name as server_name FROM federation_members fm
            JOIN servers s ON fm.server_id = s.id
            WHERE fm.federation_id = ? AND fm.status = 'active'
        """, (fed_id,)) as cur:
            return await cur.fetchall()

    async def get_pending_invites(self, server_id):
        async with self._conn.execute("""
            SELECT fm.*, f.name as fed_name FROM federation_members fm
            JOIN federations f ON fm.federation_id = f.id
            WHERE fm.server_id = ? AND fm.status = 'pending'
        """, (server_id,)) as cur:
            return await cur.fetchall()

    async def invite_to_federation(self, mem_id, fed_id, server_id, invited_by):
        await self._conn.execute("""
            INSERT OR IGNORE INTO federation_members (id, federation_id, server_id, status, invited_by)
            VALUES (?, ?, ?, 'pending', ?)
        """, (mem_id, fed_id, server_id, invited_by))
        await self._conn.commit()

    async def update_federation_status(self, fed_id, server_id, status, consented_by=None):
        await self._conn.execute("""
            UPDATE federation_members SET status = ?, consented_by = ?
            WHERE federation_id = ? AND server_id = ?
        """, (status, consented_by, fed_id, server_id))
        await self._conn.commit()

    async def transfer_federation(self, fed_id, new_owner_server_id):
        await self._conn.execute("UPDATE federations SET owner_server_id = ? WHERE id = ?", (new_owner_server_id, fed_id))
        await self._conn.commit()

    async def delete_federation(self, fed_id):
        await self._conn.execute("DELETE FROM federation_members WHERE federation_id = ?", (fed_id,))
        await self._conn.execute("DELETE FROM federations WHERE id = ?", (fed_id,))
        await self._conn.commit()

    # ── Ban Relay ──────────────────────────────────────────────────────────────

    async def set_ban_relay(self, federation_id, server_id, enabled, auto_ban=False):
        await self._conn.execute("""
            INSERT INTO ban_relay_config (id, federation_id, server_id, enabled, auto_ban)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(federation_id, server_id) DO UPDATE SET enabled=excluded.enabled, auto_ban=excluded.auto_ban
        """, (str(uuid.uuid4()), federation_id, server_id, 1 if enabled else 0, 1 if auto_ban else 0))
        await self._conn.commit()

    async def get_ban_relay_config(self, federation_id, server_id):
        async with self._conn.execute("""
            SELECT * FROM ban_relay_config WHERE federation_id = ? AND server_id = ?
        """, (federation_id, server_id)) as cur:
            return await cur.fetchone()

    async def add_ban_relay_exclusion(self, exc_id, federation_id, server_id, user_id, excluded_by):
        await self._conn.execute("""
            INSERT OR IGNORE INTO ban_relay_excluded (id, federation_id, server_id, user_id, excluded_by)
            VALUES (?, ?, ?, ?, ?)
        """, (exc_id, federation_id, server_id, user_id, excluded_by))
        await self._conn.commit()

    async def is_ban_relay_excluded(self, federation_id, server_id, user_id):
        async with self._conn.execute("""
            SELECT 1 FROM ban_relay_excluded WHERE federation_id = ? AND server_id = ? AND user_id = ?
        """, (federation_id, server_id, user_id)) as cur:
            return await cur.fetchone() is not None

    async def save_ban_relay(self, relay_id, federation_id, user_id, banned_in_server, reason=None):
        await self._conn.execute("""
            INSERT OR IGNORE INTO ban_relay (id, federation_id, user_id, banned_in_server, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (relay_id, federation_id, user_id, banned_in_server, reason))
        await self._conn.commit()

    async def mark_ban_relay_unbanned(self, federation_id, user_id, banned_in_server):
        await self._conn.execute("""
            UPDATE ban_relay SET unbanned_at = CURRENT_TIMESTAMP
            WHERE federation_id = ? AND user_id = ? AND banned_in_server = ? AND unbanned_at IS NULL
        """, (federation_id, user_id, banned_in_server))
        await self._conn.commit()

    # ── Role Mappings ──────────────────────────────────────────────────────────

    async def add_role_mapping(self, map_id, fed_id, src_sv, src_role, tgt_sv, tgt_role):
        await self._conn.execute("""
            INSERT OR IGNORE INTO role_mappings
            (id, federation_id, source_server_id, source_role_id, target_server_id, target_role_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (map_id, fed_id, src_sv, src_role, tgt_sv, tgt_role))
        await self._conn.commit()

    async def get_role_mappings(self, server_id):
        async with self._conn.execute("""
            SELECT * FROM role_mappings WHERE source_server_id = ? OR target_server_id = ?
        """, (server_id, server_id)) as cur:
            return await cur.fetchall()

    async def get_role_mappings_for_target(self, target_server_id):
        async with self._conn.execute("""
            SELECT * FROM role_mappings WHERE target_server_id = ? AND active = 1
        """, (target_server_id,)) as cur:
            return await cur.fetchall()

    async def delete_role_mapping(self, map_id):
        await self._conn.execute("DELETE FROM role_mappings WHERE id = ?", (map_id,))
        await self._conn.commit()

    async def toggle_role_mapping(self, map_id):
        await self._conn.execute(
            "UPDATE role_mappings SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (map_id,)
        )
        await self._conn.commit()

    # ── Blacklist ──────────────────────────────────────────────────────────────

    async def add_blacklist(self, bl_id, server_id, blocked_id):
        await self._conn.execute(
            "INSERT OR IGNORE INTO server_blacklist (id, server_id, blocked_server_id) VALUES (?, ?, ?)",
            (bl_id, server_id, blocked_id)
        )
        await self._conn.commit()

    async def remove_blacklist(self, server_id, blocked_id):
        await self._conn.execute(
            "DELETE FROM server_blacklist WHERE server_id = ? AND blocked_server_id = ?",
            (server_id, blocked_id)
        )
        await self._conn.commit()

    async def get_blacklist(self, server_id):
        async with self._conn.execute(
            "SELECT * FROM server_blacklist WHERE server_id = ?", (server_id,)
        ) as cur:
            return await cur.fetchall()

    async def is_blacklisted(self, server_id, other_id):
        async with self._conn.execute("""
            SELECT 1 FROM server_blacklist
            WHERE (server_id = ? AND blocked_server_id = ?)
               OR (server_id = ? AND blocked_server_id = ?)
        """, (server_id, other_id, other_id, server_id)) as cur:
            return await cur.fetchone() is not None

    # ── Audit Log ──────────────────────────────────────────────────────────────

    async def log_action(self, log_id, server_id, actor_id, action, details=None, success=True):
        await self._conn.execute("""
            INSERT INTO audit_log (id, server_id, actor_id, action, details, success)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (log_id, server_id, actor_id, action, json.dumps(details) if details else None, 1 if success else 0))
        await self._conn.commit()

    # ── Stats & Leaderboards ───────────────────────────────────────────────────

    async def get_global_stats(self):
        stats = {}
        async with self._conn.execute("SELECT COUNT(*) as cnt FROM servers WHERE bot_kicked = 0") as cur:
            stats['servers'] = (await cur.fetchone())['cnt']
        async with self._conn.execute("SELECT COUNT(*) as cnt FROM channel_bridges WHERE active = 1") as cur:
            stats['bridges'] = (await cur.fetchone())['cnt']
        async with self._conn.execute("SELECT COUNT(*) as cnt FROM message_map") as cur:
            stats['messages_relayed'] = (await cur.fetchone())['cnt']
        async with self._conn.execute("SELECT COUNT(*) as cnt FROM federations") as cur:
            stats['federations'] = (await cur.fetchone())['cnt']
        return stats

    async def leaderboard_bridges(self):
        async with self._conn.execute("""
            SELECT server_id, s.name as server_name, COUNT(*) as bridge_count
            FROM (
                SELECT channel_a_server_id as server_id FROM channel_bridges WHERE active = 1
                UNION ALL
                SELECT channel_b_server_id as server_id FROM channel_bridges WHERE active = 1
            ) b
            JOIN servers s ON b.server_id = s.id
            WHERE s.bot_kicked = 0
            GROUP BY server_id
            ORDER BY bridge_count DESC
            LIMIT 10
        """) as cur:
            return await cur.fetchall()

    async def leaderboard_messages(self):
        async with self._conn.execute("""
            SELECT server_id, s.name as server_name, COUNT(*) as msg_count
            FROM message_map mm
            JOIN servers s ON mm.original_server_id = s.id
            WHERE s.bot_kicked = 0
            GROUP BY server_id
            ORDER BY msg_count DESC
            LIMIT 10
        """) as cur:
            return await cur.fetchall()

    async def leaderboard_federations(self):
        async with self._conn.execute("""
            SELECT f.id, f.name, COUNT(fm.server_id) as member_count
            FROM federations f
            JOIN federation_members fm ON f.id = fm.federation_id
            WHERE fm.status = 'active'
            GROUP BY f.id
            ORDER BY member_count DESC
            LIMIT 10
        """) as cur:
            return await cur.fetchall()

    async def leaderboard_bridge_activity(self):
        async with self._conn.execute("""
            SELECT mm.bridge_id, cb.channel_a_id, cb.channel_b_id, COUNT(*) as msg_count
            FROM message_map mm
            JOIN channel_bridges cb ON mm.bridge_id = cb.id
            GROUP BY mm.bridge_id
            ORDER BY msg_count DESC
            LIMIT 10
        """) as cur:
            return await cur.fetchall()

    async def server_bridge_count(self, server_id):
        async with self._conn.execute("""
            SELECT COUNT(*) as cnt FROM channel_bridges
            WHERE (channel_a_server_id = ? OR channel_b_server_id = ?) AND active = 1
        """, (server_id, server_id)) as cur:
            return (await cur.fetchone())['cnt']

    async def server_message_count(self, server_id):
        async with self._conn.execute("""
            SELECT COUNT(*) as cnt FROM message_map WHERE original_server_id = ?
        """, (server_id,)) as cur:
            return (await cur.fetchone())['cnt']

    async def server_bridge_rank(self, server_id):
        rows = await self.leaderboard_bridges()
        for i, row in enumerate(rows):
            if row['server_id'] == server_id:
                return i + 1
        return None

    async def server_message_rank(self, server_id):
        rows = await self.leaderboard_messages()
        for i, row in enumerate(rows):
            if row['server_id'] == server_id:
                return i + 1
        return None

    async def get_server_config_export(self, server_id):
        server = await self.get_server(server_id)
        bridges = await self.get_bridges_for_server(server_id)
        feds = await self.get_federations_for_server(server_id)
        mappings = await self.get_role_mappings(server_id)
        bl = await self.get_blacklist(server_id)
        return {
            'server': dict(server) if server else {},
            'bridges': [dict(b) for b in bridges],
            'federations': [dict(f) for f in feds],
            'role_mappings': [dict(m) for m in mappings],
            'blacklist': [dict(b) for b in bl],
        }

    async def close(self):
        if self._conn:
            await self._conn.close()
