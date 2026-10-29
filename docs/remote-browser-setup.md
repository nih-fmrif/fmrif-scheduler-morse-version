# Remote Browser Setup (SSH SOCKS Split Tunnel)

This guide documents the working setup for browsing the staging app from a
local machine when app and Entra/OIDC traffic must traverse NIH-reachable
network paths.

This setup uses:
- SSH dynamic forwarding (`-D`) as a local SOCKS5 proxy
- A PAC file for split-tunnel behavior (route only selected domains through SSH)
- System proxy auto-config so Safari can use the split tunnel

## Prerequisites

- Working SSH access with jump hosts configured in `~/.ssh/config`
- Reachable SSH target inside NIH network (example: `sched-nih` or another host
  that can reach the app endpoint)
- Python 3 on local machine (for serving PAC file locally)

## 1. Add a SOCKS SSH host

Add a dedicated entry to local `~/.ssh/config`:

```sshconfig
Host nih-socks
    HostName 10.150.254.15
    User leejo
    IdentityFile ~/.ssh/nih-external-vendor-pai
    ProxyJump bastion-admin-external,contact004@example.org
    DynamicForward 127.0.0.1:1080
    ExitOnForwardFailure yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ForwardX11 no
```

## 2. Start the SOCKS tunnel

```bash
ssh -o ForwardX11=no -N nih-socks
```

For troubleshooting, use:

```bash
ssh -o ForwardX11=no -vvN nih-socks
```

## 3. Create a PAC file for split tunneling

Create `~/.proxy/nih-split.pac`:

```javascript
function FindProxyForURL(url, host) {
  host = host.toLowerCase();

  if (
    dnsDomainIs(host, ".nimh.nih.gov") ||
    host === "login.microsoftonline.com" ||
    dnsDomainIs(host, ".microsoftonline.com") ||
    dnsDomainIs(host, ".msauth.net") ||
    dnsDomainIs(host, ".msftauth.net") ||
    dnsDomainIs(host, ".microsoftonline-p.com") ||
    dnsDomainIs(host, ".live.com")
  ) {
    return "SOCKS 127.0.0.1:1080";
  }

  return "DIRECT";
}
```

Notes:
- Keep app host(s) and Entra/OIDC hosts in the SOCKS list.
- Add additional Entra domains if redirects fail on a new host.

## 4. Serve the PAC file locally

```bash
mkdir -p ~/.proxy
python3 -m http.server 8765 --bind 127.0.0.1 --directory ~/.proxy
```

## 5. Enable system auto-proxy config (Safari-compatible)

Find the network service name:

```bash
networksetup -listallnetworkservices
```

Set PAC URL (replace `Wi-Fi` if needed):

```bash
networksetup -setautoproxyurl "Wi-Fi" "http://127.0.0.1:8765/nih-split.pac"
networksetup -setautoproxystate "Wi-Fi" on
```

Verify:

```bash
scutil --proxy | grep -E 'ProxyAutoConfigEnable|ProxyAutoConfigURLString'
```

Expected:
- `ProxyAutoConfigEnable : 1`
- PAC URL set to `http://127.0.0.1:8765/nih-split.pac`

## 6. Validate before opening browser

Test app via SOCKS:

```bash
curl --proxy socks5h://127.0.0.1:1080 -I https://scheduler.example.test/
```

Test OIDC discovery via SOCKS:

```bash
curl --proxy socks5h://127.0.0.1:1080 \
  "https://login.microsoftonline.com/replace-with-entra--tenant-id/v2.0/.well-known/openid-configuration"
```

Success criteria:
- App returns HTTP response (for unauthenticated root path, `401` is acceptable)
- OIDC discovery returns `200` JSON

## 7. Certificate caveat

If app works with `curl -k` but fails without `-k` and fails in Safari:
- TLS certificate is likely invalid/expired/untrusted.
- `ssl-cert-snakeoil.pem` is a self-signed placeholder cert and is not suitable
  for normal browser trust.
- Deploy a valid cert chain for
  `scheduler.example.test` (or appropriate wildcard) and
  matching private key in nginx.

## 8. Disable when done

Disable PAC proxy:

```bash
networksetup -setautoproxystate "Wi-Fi" off
```

Stop local PAC server and SSH tunnel processes.
