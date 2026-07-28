// Test fixture: a task that always fails.
export default function run() {
  throw new Error('intentional crash for testing');
}
