# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Count only source spans against the token limit, excluding the synthetic final newline.
- Apply line highlight colors and font styles to gaps in caller-supplied token spans.

### Changed

- Expand shared grammar includes once per scan while preserving rule priority.
- Reduce temporary object creation during tokenization and rendering, and simplify single-capture styling.

## [0.1.0] - 2026-09-21

### Added

- Initial release

[Unreleased]: https://github.com/depthbomb/hilite/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/depthbomb/hilite/releases/tag/v0.1.0
