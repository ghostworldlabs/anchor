# wait

**When:** a worker started something itself (a process, a skill run writing a result file, a build writing a log)
and must wait for it. Use this ONE foreground command instead of a sleep/poll loop or a background command left
running. **A steward never waits on its own Anchor jobs** - it ends its turn and Anchor wakes it.

**Command:** `python C:/dev/foundry-tools/ft.py wait --pid N | --file PATH [--stable-s S] | --log PATH --line REGEX  [--max-min M]`

**Time:** as long as the thing takes; it costs no model turns while it waits.

Prints one line. Exit 0 done; 1 the time limit passed (nothing is stopped); 2 bad arguments.
