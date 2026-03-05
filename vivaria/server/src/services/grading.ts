import { execSync } from 'child_process'
import path from 'path'
import { Config } from './Config'
import { DBRuns } from './db/DBRuns'

export class GradingService {
  constructor(
    private config: Config,
    private dbRuns: DBRuns,
  ) {}

  async gradeRun(runId: number): Promise<void> {
    try {
      console.log(`Starting grading for run ${runId}`)

      // Allow override, otherwise resolve from repo root.
      const scriptPath =
        process.env.VIVARIA_GRADING_SCRIPT_PATH ??
        path.resolve(process.cwd(), '..', '..', 'scripts', 'grade_agent_logs_db.py')

      // Get OpenAI API key from environment or config
      const openaiKey = process.env.OPENAI_API_KEY || ''

      if (!openaiKey) {
        console.warn(`Grading skipped for run ${runId}: No OpenAI API key configured`)
        return
      }

      // Execute the grading script
      const command = `python3 ${scriptPath} --run-id ${runId} --model gpt-5 --json`

      let result
      try {
        const output = execSync(command, {
          encoding: 'utf8',
          timeout: 60000, // 60 second timeout
          env: { ...process.env, OPENAI_API_KEY: openaiKey },
        })
        result = JSON.parse(output)
      } catch (error: any) {
        // If the script exits with code 1 (FAIL grade), it's not an error
        if (error.status === 1 && error.stdout) {
          try {
            result = JSON.parse(error.stdout)
          } catch {
            throw error
          }
        } else {
          throw error
        }
      }

      // Store the grading result in the run's metadata
      const run = await this.dbRuns.get(runId)
      if (!run) {
        console.error(`Run ${runId} not found`)
        return
      }

      const metadata = run.metadata || {}
      metadata.grading = {
        result: result.result,
        reasoning: result.reasoning,
        gradedAt: new Date().toISOString(),
        statistics: result.statistics,
      }

      await this.dbRuns.update(runId, { metadata })
      console.log(`Grading completed for run ${runId}: ${result.result}`)

    } catch (error) {
      console.error(`Failed to grade run ${runId}:`, error)
      // Don't throw - grading failure shouldn't break the submission flow
    }
  }

  // Async wrapper that doesn't block
  gradeRunAsync(runId: number): void {
    // Fire and forget - don't await
    this.gradeRun(runId).catch(error => {
      console.error(`Async grading failed for run ${runId}:`, error)
    })
  }
}
