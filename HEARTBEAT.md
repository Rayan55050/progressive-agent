# Heartbeat Tasks

# These tasks run automatically every 30 minutes (configurable in agent.toml).
# The agent uses ALL its tools to complete them.
# Add/remove tasks — changes apply on next heartbeat cycle.

- Check free disk space on the main drive. Alert if less than 10 GB.
- Check internet connectivity (ping google.com). Alert if offline.
