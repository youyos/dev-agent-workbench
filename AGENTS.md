# Project instructions

- Keep the agent pipeline provider-neutral; OpenAI is one provider, not the runtime itself.
- Mentions must remain structured objects from UI to resolver.
- Never place secrets in prompts, events, or frontend responses.
- Every capability selection must include a user-visible reason.
- Add tests for new resolvers, routing rules, and event contracts.
- Do not run tests by default. Only execute tests when the user explicitly asks for testing; otherwise state that tests were not run.
- Imported Skill files are instructions and assets only; never execute bundled scripts automatically.
- MCP credentials remain server-side and must be redacted from list and event responses.
