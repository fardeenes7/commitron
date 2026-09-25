# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected security vulnerability. Contact the repository maintainers privately using the security contact listed in the GitHub repository settings. Include reproduction steps and the affected version where possible.

## Security notes

`commitron` transmits the current Git diff to the configured model provider. Treat diffs and API keys as sensitive. Keys are read from the process environment or a hidden interactive prompt and are not persisted by this application. Never paste secrets into issue reports.
