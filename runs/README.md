# runs

Output of test and pipeline runs: screenshots, evidence, reports, and the context and intent files. The owner's rules (adopted 2026-11-16):

1. Run output goes here, committed. It never goes to temporary folders or into tracked project files.
2. Files here are not overwritten or deleted. Each run writes a new, dated folder.
3. This output is used only to improve the system. It may be removed only after integrated tests have used it to find the improvements needed, and those improvements are made.

One exception, waiting on the owner: a folder whose name ends in `-private` holds output made from real logs or data that name client projects. Because this repository is public, those folders are kept on this machine and not committed (see .gitignore) until the owner decides.
