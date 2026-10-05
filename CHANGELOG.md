# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-04

### Fixed

- Fix synthetic newlines incorrectly counting toward token limits.
- Fix line highlight colors and font styles skipping gaps between tokens.

### Changed

- Avoid repeated work when expanding shared grammar includes.
- Improve tokenization and rendering performance.

### Added

- Add regression tests and a shared-include benchmark.

## [0.1.0] - 2026-09-21

### Added

- Initial release

[Unreleased]: https://github.com/depthbomb/hilite/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/depthbomb/hilite/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/depthbomb/hilite/releases/tag/v0.1.0
