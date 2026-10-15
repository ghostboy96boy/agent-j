# Security and responsible disclosure

Agent J tests AI agents and the wallet tooling they use. When a run reveals a weakness in third-party software (a wallet, an MCP server, an agent toolkit), we:

1. Report it privately to the maintainers through their published security channel.
2. Share the scenario and the evidence needed to reproduce it on regtest.
3. Wait for a fix or 90 days, whichever comes first, before publishing details.

Results about model behavior (which models follow injected instructions) are published without delay, since they are not vulnerabilities in a specific product.

To report a problem in Agent J itself, open a private security advisory on this repository.

All testing runs on regtest. Agent J never interacts with mainnet funds.
