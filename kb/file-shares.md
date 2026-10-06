# Network file shares (Samba)

## Available shares
| Share | Path | Who has access |
|---|---|---|
| Public | \\fileserver\Public | All staff, read/write |
| Finance | \\fileserver\Finance | Finance team only |
| Scans | \\fileserver\Scans | Staff who use the scanner; scans land here |

## Mapping a drive on Windows
1. Open File Explorer, right-click "This PC", choose "Map network drive".
2. Pick a letter (e.g. P:) and enter \\fileserver\Public.
3. Tick "Reconnect at sign-in" and "Connect using different credentials". Use your lab username and password.
When working remotely, connect the VPN first.

## Common problems
- "Access is denied" on Finance: access is group-based. Ask your manager to approve, then raise an Access ticket.
- "The network path was not found": you are off-site without the VPN, or the server name did not resolve. Try the IP address from the IT intranet.
- Saved the wrong version of a file: shadow copies are taken nightly. IT can restore from the last 14 days; include the full path and approximate time.
- Do not store personal data or passwords in Public. Use Finance or ask IT for a restricted folder.
