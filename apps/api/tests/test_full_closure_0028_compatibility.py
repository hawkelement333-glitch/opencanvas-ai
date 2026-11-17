"""Only the previously uncovered seeded 0028 -> 0029 recovery boundary."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config

from alembic import command
from tests.postgres_support import disposable_postgres_database


@pytest.fixture
def legacy_database():
    yield from disposable_postgres_database(upgrade_to="20260726_0028")


async def seed(url):
    connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    ids = [uuid.uuid4() for _ in range(5)]
    user, workspace, canvas, node1, node2 = ids
    try:
        await connection.execute(
            "INSERT INTO users(id,email,email_normalized,password_hash,"
            "display_name,email_verified) "
            "VALUES($1,'recovery-local@example.test','recovery-local@example.test',"
            "'not-a-login','Recovery local',true)",
            user,
        )
        await connection.execute(
            "INSERT INTO workspaces(id,owner_id,name) "
            "VALUES($1,$2,'Historical recovery workspace')",
            workspace,
            user,
        )
        await connection.execute(
            "INSERT INTO canvases(id,workspace_id,name) VALUES($1,$2,'Historical graph')",
            canvas,
            workspace,
        )
        for node in [node1, node2]:
            await connection.execute(
                "INSERT INTO nodes(id,canvas_id,type,title,text,position_x,position_y,"
                "width,height) "
                "VALUES($1,$2,'note','Retained note','Synthetic retained bytes',1,2,360,260)",
                node,
                canvas,
            )
        await connection.execute(
            "INSERT INTO edges(id,canvas_id,source_node_id,target_node_id,kind) "
            "VALUES($1,$2,$3,$4,'default')",
            uuid.uuid4(),
            canvas,
            node1,
            node2,
        )
        return ids, await graph_rows(connection)
    finally:
        await connection.close()


async def graph_rows(connection):
    result = {}
    for name in ("users", "workspaces", "canvases", "nodes", "edges"):
        values = await connection.fetch(
            "SELECT row_to_json(t)::text AS row FROM (SELECT * FROM " + name + " ORDER BY id) t"
        )
        result[name] = hashlib.sha256("\n".join(r["row"] for r in values).encode()).hexdigest()
    return result


async def verify(url, ids, before):
    connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        assert (
            await connection.fetchval("SELECT version_num FROM alembic_version") == "20260726_0029"
        )
        assert await graph_rows(connection) == before
        # 0028 did not store durable creation keys: migration must not fabricate them.
        assert (
            await connection.fetchval("SELECT count(*) FROM legacy_creation_request_identities")
            == 0
        )
        await connection.execute(
            "INSERT INTO legacy_creation_request_identities(request_id,actor_user_id,workspace_id,"
            "canvas_id,operation,idempotency_key,request_digest,result_kind,result_id) "
            "VALUES($1,$2,$3,$4,'canvas.create','new-post-recovery-key',$5,'canvas',$4)",
            uuid.uuid4(),
            ids[0],
            ids[1],
            ids[2],
            "a" * 64,
        )
        for sql in (
            "UPDATE legacy_creation_request_identities SET request_digest=request_digest",
            "DELETE FROM legacy_creation_request_identities",
        ):
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await connection.execute(sql)
        assert (
            await connection.fetchval("SELECT count(*) FROM legacy_creation_request_identities")
            == 1
        )
    finally:
        await connection.close()


def test_seeded_0028_migrates_without_rewriting_history_and_fences_new_identities(legacy_database):
    ids, before = asyncio.run(seed(legacy_database))
    api = Path(__file__).resolve().parents[1]
    config = Config(api / "alembic.ini")
    config.set_main_option("script_location", str(api / "alembic"))
    config.set_main_option("sqlalchemy.url", legacy_database)
    command.upgrade(config, "20260726_0029")
    asyncio.run(verify(legacy_database, ids, before))
