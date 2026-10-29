# Proxying and Tunneling Debugging Notes

This page catalogs the issues encountered while setting up split-tunnel browser
access to staging over SSH SOCKS, plus the command patterns that resolved them.

## Quick decision tree

1. SOCKS to OIDC works, SOCKS to app fails:
- Tunnel is up; app destination path is broken from SOCKS exit host.

2. Local PAC looks enabled, browser still fails:
- Verify the specific domain is covered in PAC.
- Check browser trust/TLS errors separately from routing.

3. App returns with `curl -k` but not with browser:
- Certificate trust problem (often expired/self-signed cert).

4. Local host probes fail unexpectedly on remote host:
- Proxy environment variables are forcing traffic through corporate proxy.

## Issues observed and interpretation

### 1) `curl: (97) connection to proxy closed`

Example:

```bash
curl --proxy socks5h://127.0.0.1:1080 -I https://scheduler.example.test/
```

Interpretation:
- SOCKS request reached SSH tunnel.
- SOCKS exit host failed to complete `connect(host:443)` and closed the stream.
- Usually means destination listener/path problem, not PAC syntax.

### 2) OIDC discovery succeeds through SOCKS

Example:

```bash
curl --proxy socks5h://127.0.0.1:1080 \
  "https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration"
```

Interpretation:
- SOCKS tunnel itself is healthy.
- Failure is app-specific path or endpoint-level.

### 3) Remote direct app probe shows connection refused

Example:

```bash
ssh sched-nih 'curl -vkI https://scheduler.example.test/'
```

Observed failure:
- `connect to 10.150.254.25 port 443 failed: Connection refused`

Interpretation:
- DNS resolves.
- No active listener on that IP:port at that time (or active reject policy).

### 4) Remote probes unexpectedly use NIH proxy

Observed output:
- `Uses proxy env variable https_proxy == 'http://scheduler.example.test:3128'`

Impact:
- HTTPS checks (even `https://127.0.0.1`) are sent to proxy with `CONNECT`,
  which can mask local listener state.

Fix:

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy <command>
```

### 5) Browser still fails after app returns from nginx

Observed healthy signals:
- `HTTP/1.1 301` from nginx on `http://127.0.0.1`
- `HTTP/1.0 401` from Flask on `127.0.0.1:5051`
- `HTTP/2 401` from app over HTTPS

Observed TLS issue:
- Served cert expired (`notAfter` in the past), or self-signed snakeoil cert.

Interpretation:
- Network and proxying are fine.
- Browser failure is certificate trust/validity.

## Commands that proved useful

### Local checks (macOS)

```bash
scutil --proxy | grep -E 'ProxyAutoConfigEnable|ProxyAutoConfigURLString'
lsof -nP -iTCP:1080 -sTCP:LISTEN
curl --proxy socks5h://127.0.0.1:1080 -I https://scheduler.example.test/
curl --proxy socks5h://127.0.0.1:1080 \
  "https://login.microsoftonline.com/replace-with-entra--tenant-id/v2.0/.well-known/openid-configuration"
```

### Remote connectivity and proxy isolation

```bash
ssh sched-nih 'curl -vkI https://scheduler.example.test/'

ssh fmrif-staging '
env | grep -i proxy || true
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  curl -vkI https://scheduler.example.test/
'
```

### Nginx and backend sanity on staging host

```bash
ssh fmrif-staging '
curl -vI http://127.0.0.1/ -H "Host: scheduler.example.test"
curl -vI http://127.0.0.1:5051/
'
```

### Certificate validation

```bash
ssh fmrif-staging '
openssl s_client -connect scheduler.example.test:443 \
  -servername scheduler.example.test -brief </dev/null
'
```

## Common pitfalls

- Running remote diagnostics locally by mistake.
- Forgetting to unset `https_proxy` for direct tests on remote hosts.
- Assuming `curl -k` success implies browser success.
- Using `ssl-cert-snakeoil.pem` as a long-term cert.
- Treating `401` as failure for unauthenticated root path (for this app, `401`
  can be expected and still indicates healthy routing/proxying).
