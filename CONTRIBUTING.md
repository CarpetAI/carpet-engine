# Contributing to Carpet Engine

Thank you for your interest in contributing to Carpet Engine! This document provides guidelines and information for contributors.

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- Git
- Firebase project (for testing)

### Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/yourusername/carpet-engine.git
   cd carpet-engine
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   ```bash
   cp env.example .env
   # Edit .env with your Firebase configuration
   ```

## 🔧 Development Workflow

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the coding standards below

3. **Test your changes:**
   ```bash
   # Run the development server
   uvicorn app.main:app --reload
   
   # Test your endpoints
   curl http://localhost:8000/health
   ```

4. **Commit your changes:**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

5. **Push and create a pull request:**
   ```bash
   git push origin feature/your-feature-name
   ```

### Commit Message Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Examples:
```bash
git commit -m "feat: add session analytics endpoint"
git commit -m "fix: resolve Firebase connection timeout"
git commit -m "docs: update API documentation"
```

## 📋 Coding Standards

### Python Code Style

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Use type hints where appropriate
- Write docstrings for functions and classes
- Keep functions small and focused

### Project Structure

- **Routers** (`app/routers/`): Handle HTTP requests and responses
- **Services** (`app/services/`): Business logic and external service interactions
- **Config** (`app/config/`): Application settings and environment variables
- **Models** (future): Data models and schemas

### Security Guidelines

- Never commit sensitive data (API keys, service account keys)
- Use environment variables for configuration
- Follow the security guidelines in [SECURITY.md](SECURITY.md)

## 🧪 Testing

### Running Tests

```bash
# Install test dependencies (when available)
pip install pytest pytest-asyncio

# Run tests
pytest

# Run tests with coverage
pytest --cov=app
```

### Writing Tests

- Write tests for new features
- Aim for good test coverage
- Use descriptive test names
- Mock external services (Firebase, OpenAI, etc.)

## 📝 Documentation

### Code Documentation

- Add docstrings to all functions and classes
- Include type hints
- Document complex business logic

### API Documentation

- Update OpenAPI documentation for new endpoints
- Include example requests and responses
- Document error codes and messages

## 🔍 Code Review Process

1. **Create a pull request** with a clear description
2. **Link any related issues** in the PR description
3. **Ensure all tests pass** before submitting
4. **Respond to review comments** promptly
5. **Squash commits** if requested

### Pull Request Checklist

- [ ] Code follows project style guidelines
- [ ] Tests are included and passing
- [ ] Documentation is updated
- [ ] No sensitive data is included
- [ ] Commit messages follow conventional format
- [ ] PR description is clear and complete

## 🐛 Reporting Issues

### Bug Reports

When reporting bugs, please include:

- **Description**: Clear description of the issue
- **Steps to reproduce**: Detailed steps to reproduce the bug
- **Expected behavior**: What you expected to happen
- **Actual behavior**: What actually happened
- **Environment**: OS, Python version, dependencies
- **Logs**: Relevant error logs (remove sensitive data)

### Feature Requests

For feature requests, please include:

- **Description**: Clear description of the feature
- **Use case**: Why this feature would be useful
- **Proposed implementation**: Any ideas on how to implement it

## 🤝 Community Guidelines

- Be respectful and inclusive
- Help others learn and grow
- Provide constructive feedback
- Follow the project's code of conduct

## 📞 Getting Help

- **Documentation**: Check the README and API docs
- **Issues**: Search existing issues before creating new ones
- **Discussions**: Use GitHub Discussions for questions
- **Security**: Report security issues privately

## 🎉 Recognition

Contributors will be recognized in:
- The project README
- Release notes
- GitHub contributors page

Thank you for contributing to Carpet Engine! 🚀 