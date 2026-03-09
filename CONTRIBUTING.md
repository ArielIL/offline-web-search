# Contributing to offline-web-search

First off, thank you for considering contributing! I originally built `offline-web-search` to solve my own bottlenecks with local agentic workflows, and I'm absolutely thrilled to have the community jump in to help make it better.

Whether it's a bug fix, a new feature, a documentation update, or even just fixing a typo, all contributions are highly appreciated!

## How to Contribute

### 1. Reporting Bugs and Requesting Features

If you find a bug or have an idea for a feature, please [open an issue](https://www.google.com/search?q=https://github.com/ArielIL/offline-web-search/issues) first.

* **Bugs:** Please include steps to reproduce, the expected behavior, and what actually happened. Logs and environment details (OS, Python version) are incredibly helpful.
* **Features:** Explain why the feature is needed and how it fits into the broader goal of making this a seamless, offline `Google Search` alternative for LLMs.

### 2. Local Development Setup

To set up the project locally for development:

1. **Fork the repository** to your own GitHub account.
2. **Clone your fork** locally:
```bash
git clone https://github.com/YOUR-USERNAME/offline-web-search.git
cd offline-web-search

```


3. **Install the dependencies** (including dev dependencies):
```bash
pip install -e ".[dev]"

```


4. **Set up your local ZIM files** and run the indexer as described in the [README](README.md).

### 3. Branch Naming Conventions

To keep the repository organized, please create a new branch for your work using the following naming conventions (`<type>/<short-description>`):

* **`feat/...`** (e.g., `feat/add-confluence-crawler`) — For adding new features or tools.
* **`fix/...`** (e.g., `fix/bm25-ranking-error`) — For bug fixes.
* **`docs/...`** (e.g., `docs/update-readme-api`) — For documentation updates.
* **`refactor/...`** (e.g., `refactor/search-engine-logic`) — For code changes that neither fix a bug nor add a feature.
* **`test/...`** (e.g., `test/add-crawler-tests`) — For adding missing tests or correcting existing ones.

```bash
git checkout -b feat/your-new-feature

```

### 4. Making Changes and Testing

* Write your code!
* Ensure your code follows standard Python PEP-8 guidelines.
* **Run the tests** before committing to make sure nothing broke. We use `pytest`:
```bash
pytest tests/ -v
pytest tests/ --cov=offline_search --cov-report=term-missing

```


* If you are adding a new feature, please try to include basic tests for it.

### 5. Submitting a Pull Request (PR)

1. Commit your changes with a clear, descriptive commit message.
2. Push your branch to your forked repository.
3. Open a Pull Request against the `master` branch of this repository.
4. In the PR description, clearly explain what you changed, why you changed it, and link to any relevant open issues.

I will review PRs as quickly as I can. Don't be offended if I ask for tweaks or changes—it's all about keeping the codebase robust and clean!

---

Once again, thanks for helping out. Let's build the best offline search tool for local LLMs!

---
