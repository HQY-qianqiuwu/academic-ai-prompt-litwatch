# Project Instructions

1. Read `docs/DIFY_ITERATION_PLAN.md` before coding.
2. `literature-search-v1.0.yml` is a stable baseline.
3. Never overwrite a stable Dify DSL.
4. New Dify versions must use new files, such as `literature-search-v1.1.yml`, `literature-search-v1.2.yml`, and later versioned files.
5. Work on one stage at a time.
6. Run tests before every commit.
7. Do not modify unrelated files.
8. Never use destructive Git commands without explicit approval.
9. Never commit API keys.
10. External literature metadata must come from real APIs.
11. The LLM must never fabricate `title`, `authors`, `DOI`, `venue`, `publication date`, or `URL`.
12. SQLite and LitWatch handle deterministic data logic.
13. Dify handles workflow orchestration and semantic analysis.
14. Every stable version must correspond to a Git tag.
