"""Reviewed KB-derived labels; reproducible authoring source, never used by retrievers."""
import json
from pathlib import Path

GROUPS = {
'vpn-wireguard': [
('Who can use the remote access tunnel?', 'Staff working remotely; contractors need manager approval.'),
('Hotel wifi says WireGard active but I cannot reach anything. What next?', 'Check Latest handshake; UDP 51820 may be blocked. Try a phone hotspot.'),
('After rebuilding my laptop the handshake works but shares fail.', 'Ask IT to revoke the old peer and issue a new config.'),
('Can I give my colleague my VPN QR code?', 'Never share a personal config; it is tied to one device.'),
('How do I import the remote access configuration?', 'Install WireGuard, import the personal file or scan QR code, enable the tunnel and test Public or the printer page.'),
('My VPN is slow while another VPN is connected.', 'Disconnect other VPNs; only one tunnel can be active.'),
('My laptop with its WireGuard profile was stolen.', 'Raise P1 immediately so IT can revoke the device peer key.')],
'file-shares': [
('Where is the Finance folder?', r'Use \\fileserver\Finance; Finance team only.'),
('Map a drive to the folder everyone can write to.', r'Map a letter to \\fileserver\Public, reconnect at sign-in, use lab credentials; connect VPN remotely.'),
('Finanace says acess denied. Can you grant access?', 'Manager approval and an Access ticket are required; access is group-based.'),
('I overwrote a file yesterday. Is it recoverable?', 'IT can restore nightly shadow copies from the last 14 days; provide full path and approximate time.'),
('Where do scanner files land?', r'Use \\fileserver\Scans.'),
('Can I keep passwords in Public?', 'Do not store passwords or personal data there; use Finance or request a restricted folder.'),
('Network path not found while away from office.', 'Connect VPN; if name resolution fails try the server IP from the IT intranet.')],
'printing': [
('How do I add Office-Laser on Windows?', 'Add device in Printers & scanners; add manually using http://printserver:631/printers/Office-Laser.'),
('My Mac needs the office printer.', 'Add via IP tab, protocol IPP, address printserver, queue printers/Office-Laser.'),
('Prnter offline, what can I check?', 'Check power, paper and screen errors; restart once.'),
('My job is stuck in the print queue.', 'Open http://printserver:631/jobs, cancel your job and print again.'),
('Pages are blank or gibberish.', 'Remove and re-add printer; use generic PCL or IPP Everywhere driver.'),
('How can I print while working from home?', 'Connect VPN first.'),
('The entire team cannot print this morning.', 'Raise a P2 ticket; likely the print server.')],
'password-mfa': [
('I forgot my password. How do I reset it?', 'Use Forgot password on self-service portal, verify registered authenticator or mobile and choose a new passphrase.'),
('How long must my new passphrase be?', 'At least 14 characters; do not reuse old passwords.'),
('Five failed logins locked me out. How long to wait?', 'Wait 15 minutes before retrying carefully.'),
('Account keeps locking after I changed the password.', 'Update old saved passwords in phone mail apps.'),
('New mobile, authenticator unavailable. Can you reset MFA?', 'Raise Access ticket; IT verifies identity by video call before reset.'),
('Lost my phone with the authenticator on it.', 'Raise Access ticket and mention lost phone as security issue so IT can sign out sessions.'),
('Typed my password into a fake mailbox warning link.', 'Change it immediately and raise P1 Security ticket.')],
'wifi-network': [
('Which SSID do staff use?', 'Office-Staff, WPA2-Enterprise, work account sign-in.'),
('Where is the guest wireless password?', 'At reception; changes monthly.'),
('Can visitors on Office-Guest reach printers?', 'Guests cannot reach printers or shares.'),
('Office wifii wont conect on my laptop.', 'Forget and reconnect, check date and time, restart Wi-Fi.'),
('Everyone has slow Internet today.', 'Raise a P2 ticket.'),
('Only my wireless connection is slow.', 'Move closer to access point and close large uploads or syncs.'),
('May I connect a personal router to a wall port?', 'Never plug personal routers or switches into office wall ports.')],
'email-outlook': [
('Outlook repeatedly asks for my password.', 'Sign out of Office, clear Windows Credential Manager saved credentials, sign in with MFA.'),
('Mailbox full, how can I clear space?', 'Use Online Archive, empty Deleted Items, remove large attachments.'),
('Granted shared mailbox access but cannot see it yet.', 'Allow about an hour then restart Outlook.'),
('Phone calendar stopped syncing.', 'Remove and re-add account in Outlook mobile.'),
('Can I email a 35 MB attachment?', 'Share a file share or OneDrive link instead of attachments over 20 MB.'),
('Outlok keeps showing the sign in box after signing in.', 'Sign out of Office, clear saved Windows credentials and sign in again; expect MFA.'),
('How long before a newly authorised shared mailbox appears?', 'About an hour after access granted; restart Outlook.')],
'onboarding-offboarding': [
('When should a manager request a new starter account?', 'At least 3 business days before start; include name, role, date and required shares.'),
('What does IT prepare for a starter on day one?', 'Account, MFA enrolment, standard laptop and file-share groups.'),
('Do all new starters automatically get VPN?', 'Only roles working remotely receive VPN access.'),
('What goes in the first day pack?', 'Wi-Fi details, printer guide and ticket instructions.'),
('What information is needed for a leaver request?', 'Manager submits Offboarding ticket with last working day.'),
('What does IT remove when someone leaves?', 'Disable account, revoke VPN peers, remove shares and collect devices on last day.'),
('Can a departing employee email be forwarded to manager?', 'For 30 days if requested.')],
'service-desk-policy': [
('What is the first response target for P1?', '15 minutes; resolution target 4 hours.'),
('Which priority is a service degraded for a whole team?', 'P2; first response 1 hour, resolution 1 business day.'),
('A single user has a workaround. What priority?', 'P3; first response 4 hours, resolution 3 business days.'),
('How are routine access requests prioritised?', 'P4; first response 1 business day, resolution 5 business days.'),
('Can the copilot automatically grant access?', 'Access changes always go to a human.'),
('Will a ticket containing sensitive data be auto sent?', 'Personal or sensitive information always goes to a human.'),
('When may a generated reply be sent automatically?', 'Low-risk P3/P4 only, confident and independently checked as fully supported.')],
}
MULTI = [
('I am new and remote. How is my VPN issued and how do I connect?', ['onboarding-offboarding','vpn-wireguard'], 'VPN is issued for remote roles; install WireGuard, import personal config and enable tunnel.'),
('From home I need the Public drive and office printer. What are the steps?', ['file-shares','printing','vpn-wireguard'], r'Connect VPN, map \\fileserver\Public using lab credentials; add Office-Laser with the printserver IPP URL.'),
('Visitor wants wireless access and the Finance folder.', ['wifi-network','file-shares'], 'Guest password is at reception; guests cannot reach shares. Finance is restricted to Finance group with manager-approved access.'),
('A stolen laptop had VPN configured. What priority and action?', ['vpn-wireguard','service-desk-policy'], 'P1 security incident, response target 15 minutes; ask IT to revoke device peer key.')]
NO_ANSWER = [
'What is the current guest Wi-Fi password?', 'What is the exact fileserver IP address?',
'How do I configure the Salesforce SAML connector?', 'Which BIOS update fixes this Dell blue screen?',
'What is our payroll portal URL?', 'How do I recover a deleted Teams channel?',
'What is the retention period for our SQL database backups?', 'Can you provide a BitLocker recovery key?',
'How do I install the company CAD licence server?', 'What SMTP port and hostname does our mail relay use?']

def main():
    rows = []
    for doc, pairs in GROUPS.items():
        for q, a in pairs:
            rows.append({'question': q, 'gold_article_ids': [doc], 'gold_answer': a,
                         'type': 'typo' if any(s in q for s in ['WireGard','Finanace','Prnter','wifii','Outlok']) else 'paraphrase'})
    rows.extend({'question':q,'gold_article_ids':g,'gold_answer':a,'type':'multi_article'} for q,g,a in MULTI)
    rows.extend({'question':q,'gold_article_ids':[],'gold_answer':'The KB does not cover this; a technician will follow up.','type':'no_answer'} for q in NO_ANSWER)
    for i, row in enumerate(rows,1):
        row['id'] = f'q{i:03d}'
        row['split'] = 'test' if i%3 == 0 else 'dev'
    Path(__file__).with_name('questions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')

if __name__ == '__main__': main()
