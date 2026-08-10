# Agent Rules

## Architecture Discovery

- Read `ARCHITECTURE.md` before changing project behavior.
- Use `docs/architecture/MODULES.md` to locate the owning functional module.
- Read the module's `ARCHITECTURE.md`, listed entrypoints, invariants and tests
  before editing implementation files.
- Keep changes inside the owning module unless cross-module impact is stated.
- Architecture documentation uses Markdown only. Do not introduce YAML or YML
  module manifests.
- Update the owning architecture document when module boundaries, contracts,
  data ownership, runtime entrypoints or debugging instructions change.

## Progress Reporting

- After every task or phase, report progress before moving on.
- A progress report must include:
  - What was completed.
  - What files or modules changed.
  - What checks/tests were run and their result.
  - What remains or is blocked.
- For long-running work, also send short status updates while working so the project owner can follow the current state.
  -1 luật bắt buộc là tạo prompt không được chèn code vào chỉ prompt logic và hướng xử lí flow.
