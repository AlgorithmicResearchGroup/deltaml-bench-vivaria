import 'dotenv/config'

import { Knex } from 'knex'
import { sql, sqlLit, withClientFromKnex } from '../services/db/db'

export async function up(knex: Knex) {
  await withClientFromKnex(knex, async conn => {
    await conn.none(sql`
      CREATE INDEX IF NOT EXISTS ${sqlLit`agent_branches_modifiedat_idx`}
      ON agent_branches_t ("modifiedAt")
    `)
  })
}

export async function down(knex: Knex) {
  await withClientFromKnex(knex, async conn => {
    await conn.none(sql`DROP INDEX IF EXISTS ${sqlLit`agent_branches_modifiedat_idx`}`)
  })
}
