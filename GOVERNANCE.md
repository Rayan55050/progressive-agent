# Project Governance

## Overview

Progressive Agent follows a **Benevolent Dictator For Life (BDFL)** governance model. This is a simple, effective model for open-source projects where one person holds final decision-making authority while actively welcoming community contributions.

## BDFL

The project is maintained by **Progressive AI** ([progressiveai.me](https://progressiveai.me)), who serves as the BDFL. The BDFL:

- Sets the project vision and roadmap.
- Has final say on all technical decisions, feature additions, and architectural changes.
- Reviews and merges (or rejects) pull requests.
- Manages releases and project infrastructure.

## How Decisions Are Made

1. **Day-to-day decisions** (bug fixes, minor improvements, documentation) are made by the BDFL or any active maintainer. No formal process needed.

2. **Feature proposals** (new tools, skills, architectural changes) follow this process:
   - Open a GitHub Discussion or Issue describing the proposal.
   - Community members and maintainers provide feedback.
   - The BDFL makes the final decision, taking community input into account.
   - Approved features are added to the roadmap.

3. **Breaking changes** (API changes, dependency overhauls, protocol modifications) are discussed openly before implementation. The BDFL aims for consensus but retains final authority.

The guiding principles for all decisions:
- **Simplicity over complexity.** Fewer abstractions, less magic.
- **Privacy first.** Local execution by default. No telemetry.
- **Pragmatism over purity.** Working code beats perfect architecture.
- **Community input matters.** The BDFL listens, even when the final call is theirs.

## Roles

### Maintainer

Maintainers have write access to the repository and can review/merge pull requests. To become a maintainer:

1. Make sustained, high-quality contributions over time.
2. Demonstrate understanding of the project's architecture and goals.
3. Be nominated by an existing maintainer and approved by the BDFL.

### Contributor

Anyone who submits a pull request, reports a bug, answers questions, or improves documentation is a contributor. Contributors are recognized in commit history and release notes.

### How to Become a Contributor

1. Read the [Contributing Guide](CONTRIBUTING.md).
2. Pick an issue labeled `good first issue` or `help wanted`.
3. Submit a pull request.
4. That's it. Your first merged PR makes you a contributor.

## Code of Conduct

All participants are expected to follow the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). Be respectful, constructive, and welcoming.

## Changes to Governance

This governance model may evolve as the project grows. Any changes will be proposed, discussed openly, and decided by the BDFL.
