# Remote access VPN (WireGuard)

## Who can use it
All staff who work from home or travel. Contractors need manager approval first (raise a ticket with category "Access").

## Getting connected
1. Install the WireGuard app (Windows, macOS, iOS, Android) from the official store or wireguard.com.
2. IT sends you a personal config file or QR code from the VPN admin console (wg-easy). Never share it; each config is tied to one device.
3. Import the file (or scan the QR code) and toggle the tunnel on.
4. Test by opening the file share \\fileserver\Public or the printer page http://printserver:631.

## Troubleshooting
- Tunnel shows "active" but nothing loads: check the "Latest handshake" time. If it never updates, your network may block UDP 51820 (hotel or guest Wi-Fi). Try a phone hotspot.
- Handshake works but shares do not open: you are probably using a stale config after a device rebuild. Ask IT to revoke the old peer and issue a new one.
- Slow speeds: disconnect from other VPNs; only one tunnel can be active.
- Lost or stolen device: raise a P1 ticket immediately so IT can revoke that device's peer key.
