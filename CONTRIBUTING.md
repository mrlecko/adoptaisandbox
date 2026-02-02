# Contributing to CSV Analyst Chat

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/yourusername/csv-analyst-chat.git
   cd csv-analyst-chat
   ```
3. **Install dependencies**:
   ```bash
   make install
   ```
4. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Workflow

### Before You Start

- Check existing issues and PRs to avoid duplicates
- For large changes, open an issue first to discuss
- Read the [implementation plan](docs/IMPLEMENTATION_PLAN.md)
- Check [TODO.md](TODO.md) for planned work

### Making Changes

1. **Follow the project structure** (see README.md)
2. **Write tests** for new features
3. **Update documentation** as needed
4. **Follow code style**:
   - Python: Black formatting + Ruff linting
   - Keep functions focused and small
   - Add docstrings for public APIs

### Running Tests

```bash
# All tests
make test

# Specific test suites
make test-unit
make test-integration
make test-security

# Code coverage
make coverage
```

### Code Quality

Before committing:

```bash
# Format code
make format

# Run linters
make lint

# Run all tests
make test
```

## Commit Guidelines

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Build process, dependencies, tooling

**Examples:**
```
feat(agent): add QueryPlan validation
fix(runner): handle timeout correctly
docs(readme): add K8s deployment guide
test(security): add SQL injection tests
```

### Good Practices

- Keep commits atomic (one logical change per commit)
- Write clear, descriptive commit messages
- Reference issues: `Fixes #123` or `Relates to #456`
- Sign commits if possible

## Pull Request Process

1. **Update your branch** with latest main:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Open a Pull Request** on GitHub with:
   - Clear title describing the change
   - Description of what changed and why
   - Link to related issues
   - Screenshots (if UI changes)
   - Test results

4. **Address review feedback**:
   - Make requested changes
   - Push updates to your branch
   - Respond to comments

5. **Merge**: Once approved, maintainers will merge your PR

## Testing Guidelines

### Unit Tests

- Test individual functions and classes
- Mock external dependencies
- Aim for >80% coverage
- Location: `tests/unit/`

### Integration Tests

- Test end-to-end flows
- Use real Docker/K8s where needed
- Test error paths
- Location: `tests/integration/`

### Security Tests

- Test validation bypasses
- SQL injection attempts
- Prompt injection
- Data exfiltration attempts
- Location: `tests/security/`

## Code Style

### Python

- Use Black for formatting (line length 100)
- Use Ruff for linting
- Follow PEP 8 conventions
- Type hints encouraged (but not required for MVP)
- Docstrings for public APIs (Google style)

Example:
```python
def compile_query_plan(plan: QueryPlan) -> str:
    """Compile a QueryPlan to deterministic SQL.

    Args:
        plan: Validated QueryPlan object

    Returns:
        SQL string ready for execution

    Raises:
        CompilationError: If plan cannot be compiled
    """
    # Implementation
```

### JavaScript/TypeScript (UI)

- Follow Next.js conventions
- Use ESLint + Prettier
- Functional components with hooks

## Documentation

Update documentation when:
- Adding new features
- Changing APIs or interfaces
- Modifying deployment process
- Adding configuration options

**Files to update:**
- `README.md` - User-facing changes
- `CLAUDE.md` - Architecture/context changes
- `CHANGELOG.md` - All notable changes
- Component READMEs - Component-specific changes
- Docstrings/comments - Code behavior changes

## Security

### Reporting Vulnerabilities

**DO NOT** open public issues for security vulnerabilities.

Instead:
1. Email maintainers directly (see README for contact)
2. Provide details of the vulnerability
3. Allow time for fix before disclosure

### Security Considerations

When contributing:
- Never commit secrets or API keys
- Validate all user inputs
- Follow principle of least privilege
- Test sandbox escape scenarios
- Review SQL injection vectors

## Adding Features

### New Query DSL Features

1. Update `models/query_plan.py` with new schema
2. Update compiler in `validators/compiler.py`
3. Add validation logic
4. Write tests (good + bad cases)
5. Update documentation
6. Add example prompts

### New Dataset

1. Follow structure in `datasets/README.md`
2. Create directory with CSVs
3. Update `registry.json`
4. Add 4-6 example prompts
5. Generate version hash
6. Test with agent

### New Executor

1. Implement `Executor` interface from `executors/base.py`
2. Handle lifecycle (submit, poll, cleanup)
3. Enforce security context
4. Write integration tests
5. Update configuration

## Questions?

- Open an issue for questions
- Check existing issues/PRs
- Read [CLAUDE.md](CLAUDE.md) for architecture context
- Review [docs/](docs/) for detailed plans

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

Thank you for contributing! 🎉
