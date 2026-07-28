# Labeled corpus — hand-labeled remove/keep ground truth

Started in Wave 2 so the Wave-9 heuristic precision gate has data to measure
against. Heuristic mode does not ship enabled until it clears that bar, and a
bar with no measurement behind it is a slogan.

## Why the folders are JSON, not checked-in directories

Two reasons, both load-bearing:

1. **git does not preserve mtimes.** A checked-in corpus would arrive on every
   machine with a fresh timestamp, so the `age` heuristic — one of the four —
   could never fire against it, and the gate would silently be measuring three
   heuristics while claiming to measure four. Each file therefore declares
   `ageDays`, and the harness stamps the mtime when it materialises the folder.
2. **A corpus of secrets and junk in the repository is itself a hazard.** The
   fixtures materialise into a temp directory, get measured, and are removed.

## Format

`index.json` lists the corpus members. Each member file is:

```jsonc
{
  "id": "01-abandoned-prototype",
  "description": "what real-world mess this folder is a specimen of",
  "mode": "heuristic",          // the run mode this folder should select
  "git": false,                 // whether the harness should `git init` it
  "files": [
    { "path": "src/app.mjs", "content": "...", "ageDays": 3 }
  ],
  "labels": [
    { "path": "src/app.mjs", "truth": "keep", "why": "the live entry point" }
  ]
}
```

`truth` is one of `remove` / `keep`. **Every** file in `files` must carry a
label — a partially labeled folder would let a miss hide in the unlabeled
remainder, and `test/corpus.test.mjs` fails the build if any file is unlabeled.

`06-legit-small-project` is the negative control: every label is `keep`. A
corpus without one measures recall while pretending to measure precision.

## Adding a folder

Add the file, add its id to `index.json`. Label honestly — including the cases
where you would not actually delete the file. The gate is only worth having if
the labels are what you would really do.
