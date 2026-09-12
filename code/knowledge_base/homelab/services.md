# Homelab Services Reference

## Core Services
- **LLM Proxy** (port 8080): OpenAI-compatible API for AI requests
- **Local LLM** (port 18090): Gemma 3 12B Q4_K_M for private processing
- **MCP Gateway** (port 8090): Central hub for all MCP services
- **Hermes Web UI** (port 8787): Main interface for Hermes agent

## Monitoring Stack
- **Prometheus** (port 9090): Metrics collection and storage
- **Grafana** (port 3002): Visualization and dashboards
- **Loki** (port 3100): Log aggregation
- **cAdvisor** (port 8081): Container metrics
- **Node Exporter** (port 9101): Host metrics

## Media & Entertainment
- **Immich** (port 2283): Photo and video backup solution
- **Paperless** (port 8000): Document management system
- **Calibre-Web** (port 8083): E-book library and reader
- **Seafile**: File synchronization and sharing
- **Plex/Jellyfin**: Media streaming (if configured)

## Productivity & Utilities
- **Vaultwarden** (port 8443): Password manager
- **Homepage** (port 3000): Personal dashboard and start page
- **Pi-hole** (port 8053): Network-wide ad blocking
- **OpenWebUI** (port 8082): Chat interface for LLMs
- **ChangeDetection.io** (port 5000): Website change monitoring
- **OpenViking**: Personal knowledge and context database
- **SearXNG** (port 8118): Privacy-respecting metasearch engine

## Development & CI/CD
- **Gitea**: Self-hosted Git service
- **Drone CI**: Continuous integration platform
- **Portainer** (port 9000): Docker container management
- **Watchtower**: Automatic container updates
- **Qdrant** (port 6333): Vector database for AI applications

## Network & Security
- **WireGuard**: VPN for secure remote access
- **Fail2Ban**: Intrusion prevention framework
- **Unattended Upgrades**: Automatic security patches
- **Smartmontools**: Disk health monitoring
