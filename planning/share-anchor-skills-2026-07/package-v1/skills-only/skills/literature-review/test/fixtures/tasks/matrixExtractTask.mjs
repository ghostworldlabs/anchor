// Test fixture: simulated per-source matrix extraction inside an isolated
// worker — emits per-column progress telemetry and reports its own pid so the
// scheduler tests can prove real process-level parallelism.
export default async function run(input, ctx) {
  ctx.log(`matrix extraction started: ${input.paperId} (depth ${input.depth})`);
  const columns = input.columns ?? [];
  const extracted = {};
  for (let i = 0; i < columns.length; i++) {
    const column = columns[i];
    extracted[column] = input.values?.[column] ?? null;
    ctx.progress(i + 1, columns.length, `extracted ${column}`);
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  return {
    pid: process.pid,
    batchId: input.batchId,
    paperId: input.paperId,
    depth: input.depth,
    extracted
  };
}
