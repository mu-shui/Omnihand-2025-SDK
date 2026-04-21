# Firmware Validation Scripts

This directory contains firmware validation code for OmniHand devices.

## Scope

- Validate joint control and feedback behavior.
- Validate communication quality and timing stability.
- Capture validation logs and artifacts for regression checks.

## Location

- Validation code root: `/home/agiuser/文档/Omnihand-2025-SDK-dev-release/scripts/validation`

## Typical Script Categories

- Joint sweep and range validation.
- Communication frequency and packet-loss checks.
- Feedback frequency and timestamp consistency checks.

## Notes

- Most scripts require a connected OmniHand device and CANFD adapter.
- Run scripts from this directory to keep output files grouped with validation artifacts.
