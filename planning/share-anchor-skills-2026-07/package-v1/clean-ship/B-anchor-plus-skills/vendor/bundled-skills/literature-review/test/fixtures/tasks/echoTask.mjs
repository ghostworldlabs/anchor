// Test fixture: a well-behaved worker task emitting progress and a result.
export default async function run(input, ctx) {
  ctx.log(`echo task started: ${input.label}`);
  const steps = input.steps ?? 3;
  for (let i = 1; i <= steps; i++) {
    ctx.progress(i, steps, `step ${i} of ${steps}`);
  }
  return { echoed: input.label, steps, workerId: ctx.workerId };
}
