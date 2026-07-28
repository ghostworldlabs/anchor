// Test fixture: a task that never resolves (exercises the parent's timeout kill).
export default function run() {
  return new Promise(() => {});
}
