# Printing (CUPS print server)

## Adding the office printer
- Windows: Settings > Bluetooth & devices > Printers & scanners > Add device. If it is not found, choose "Add manually" and enter http://printserver:631/printers/Office-Laser.
- macOS: System Settings > Printers & Scanners > Add, choose the IP tab, protocol IPP, address printserver, queue printers/Office-Laser.
- A PDF printer (queue "Office-PDF") is also available for testing and for saving print jobs as PDFs to the Scans share.

## Troubleshooting
1. Job stuck in the queue: open http://printserver:631/jobs, cancel your job, then print again.
2. "Printer offline": check the printer has power and paper and the screen shows no error. Restart it once.
3. Prints blank or garbled: remove and re-add the printer to refresh the driver (use the generic PCL or IPP Everywhere driver).
4. Printing from home: connect to the VPN first.
If several people cannot print at once, raise a P2 ticket; it is probably the print server, not your PC.
