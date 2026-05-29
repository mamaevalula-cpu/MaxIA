#!/usr/bin/env python3
"""
Auto-configure Namecheap DNS for Resend email verification.
Run after enabling API access in Namecheap profile settings.
Usage: python3 setup_namecheap_dns.py <api_key>
"""
import sys, os, urllib.request, urllib.parse, xml.etree.ElementTree as ET

DOMAIN = "maxai.fyi"
SLD = "maxai"
TLD = "fyi"
API_USER = "maxinternet"
CLIENT_IP = "77.90.2.171"

DKIM_VALUE = "p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCt52k4z7lyGhCkx1Ru6pPc0IthA9SJndYxEWxMG6cC13WlHMvp3IZhNLZ9utUwKQbXp19PaGA5gwbedv7Jy+Kua1MYX19Ci/GwKEE22jcFDno78uR6RVZhqqDkTGRn5FOjni+BLE/6eR1c6fL+7rNIQmjcGgeLXloztdaUQVLnQwIDAQAB"

RECORDS = [
    ("resend._domainkey", "TXT", DKIM_VALUE, "10", "1800"),
    ("send",              "MX",  "feedback-smtp.us-east-1.amazonses.com", "10", "1800"),
    ("send",              "TXT", "v=spf1 include:amazonses.com ~all", "10", "1800"),
]

def call_api(api_key, **extra_params):
    params = {
        "ApiUser": API_USER,
        "ApiKey": api_key,
        "UserName": API_USER,
        "ClientIp": CLIENT_IP,
        **extra_params
    }
    url = "https://api.namecheap.com/xml.response?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        return ET.fromstring(r.read())

def get_existing_records(api_key):
    tree = call_api(api_key,
        Command="namecheap.domains.dns.getHosts",
        SLD=SLD, TLD=TLD)
    hosts = tree.findall(".//{http://api.namecheap.com/xml.response}host")
    return [(h.get("Name"), h.get("Type"), h.get("Address")) for h in hosts]

def set_all_records(api_key, existing):
    """Merge existing + new records and set all at once."""
    all_records = list(existing)
    for name, rtype, addr, mx, ttl in RECORDS:
        if not any(e[0] == name and e[1] == rtype for e in existing):
            all_records.append((name, rtype, addr, mx, ttl))
    params = {"Command": "namecheap.domains.dns.setHosts", "SLD": SLD, "TLD": TLD}
    for i, rec in enumerate(all_records, 1):
        if len(rec) == 3:
            name, rtype, addr = rec
            mx_pref, ttl = "10", "1800"
        else:
            name, rtype, addr, mx_pref, ttl = rec
        params[f"HostName{i}"] = name
        params[f"RecordType{i}"] = rtype
        params[f"Address{i}"] = addr
        params[f"MXPref{i}"] = mx_pref
        params[f"TTL{i}"] = ttl
    tree = call_api(api_key, **params)
    status = tree.get("Status")
    errors = tree.findall(".//{http://api.namecheap.com/xml.response}Error")
    return status, [e.text for e in errors]

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 setup_namecheap_dns.py <namecheap_api_key>")
        print(f"Domain: {DOMAIN}")
        print("Records to add:")
        for name, rtype, addr, *_ in RECORDS:
            print(f"  {rtype} {name}.{DOMAIN} -> {addr[:50]}...")
        sys.exit(1)
    api_key = sys.argv[1]
    print(f"Configuring DNS for {DOMAIN}...")
    try:
        existing = get_existing_records(api_key)
        print(f"Existing records: {len(existing)}")
        status, errors = set_all_records(api_key, existing)
        print(f"Status: {status}")
        if errors:
            print(f"Errors: {errors}")
        else:
            print("SUCCESS: All 3 DNS records added!")
            print("Now go to Resend and click Verify DNS Records")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
