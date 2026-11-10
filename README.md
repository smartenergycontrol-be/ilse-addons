# ILSE add-ons

Home Assistant add-ons by [Smart Energy Control](https://www.smartenergycontrol.be).

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fsmartenergycontrol-be%2Filse-addons)

## Add-ons

| Add-on | Description |
| --- | --- |
| [Tailscale](tailscale/) | Secure remote connection over Tailscale or a self-hosted control server. Based on [hass-tailscale/hass-addons](https://github.com/hass-tailscale/hass-addons). |

## Installation

1. In Home Assistant go to Settings > Apps > App store, open the menu (three dots) and choose Repositories.
2. Add `https://github.com/smartenergycontrol-be/ilse-addons`.
3. Install the add-on, fill in its configuration and start it.

## Tailscale options

| Option | Example | Meaning |
| --- | --- | --- |
| `auth_key` | `tskey-...` | Pre-auth key from your control server (required) |
| `login_server` | `https://headscale.example.com` | Control server URL |
| `hostname` | `my-home` | Name of this device on the tailnet |
| `userspace_networking` | `false` | `false` creates a `tailscale0` interface on the host |
| `accept_routes` | `false` | Accept subnet routes from other nodes |

All other options are documented in [tailscale/DOCS.md](tailscale/DOCS.md).

## Credits

The Tailscale add-on is a fork of [hass-tailscale/hass-addons](https://github.com/hass-tailscale/hass-addons).
