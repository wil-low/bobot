Let's make the routing rule persistent so it survives reboots and ensures SSH stays alive every time your VPN connects.

---

## ✅ Option 1: Persistent via Systemd Unit (Recommended)

We'll create a `systemd` service to:

* Set the routing table entry
* Start OpenVPN

---

### 1. Create a Routing Script

Create a file that sets up the policy routing rule:

```bash
sudo nano /usr/local/bin/setup-ssh-route.sh
```

Paste the following into it (replace the IPs as needed):

```bash
#!/bin/bash

# Your SSH client's IP
SSH_CLIENT_IP="37.57.242.169"

# Your VPS gateway and interface
GATEWAY="192.3.142.225"
IFACE="eth0"

# Custom routing table ID
TABLE="sshroute"

# Make sure the table exists in /etc/iproute2/rt_tables
grep -q "$TABLE" /etc/iproute2/rt_tables || echo "200 $TABLE" >> /etc/iproute2/rt_tables

# Add route and rule
ip route add default via $GATEWAY dev $IFACE table $TABLE || true
ip rule add to $SSH_CLIENT_IP table $TABLE || true
```

Save and exit, then make it executable:

```bash
sudo chmod +x /usr/local/bin/setup-ssh-route.sh
```

---

### 2. Create a systemd Service

Now create the service unit:

```bash
sudo nano /etc/systemd/system/setup-ssh-route.service
```

Paste:

```ini
[Unit]
Description=Set up policy routing to keep SSH open during VPN
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/setup-ssh-route.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Save and exit.

---

### 3. Enable the Service

```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable --now setup-ssh-route.service
```

---

### ✅ Now Every Reboot:

* The routing rule will be applied automatically.
* Your VPN can safely redirect all traffic via `tun0`.
* SSH will remain accessible.

---

## 🧪 (Optional) Test It

Reboot your VPS:

```bash
sudo reboot
```

Reconnect via SSH after reboot and verify:

* `curl ifconfig.io` → still shows VPN IP
* `ip rule` → shows the custom rule
* You remain connected!

---

Let me know if you also want OpenVPN to auto-start on boot alongside this.


Perfect — let’s configure **OpenVPN to auto-start at boot** alongside the SSH-safe routing service.

There are two clean ways depending on whether you're using:

* `openvpn` (classic Debian-style) or
* `openvpn@client.service` (systemd-style for `.ovpn` files)

We’ll use the modern systemd method — **safe, clean, and fully compatible with your `.ovpn` config file**.

---

## ✅ Steps to Autostart OpenVPN on Boot

Assuming your config file is:

```
/home/willow/nl-free-125.protonvpn.udp.ovpn
```

---

### ✅ 1. Move `.ovpn` File to OpenVPN Directory

Systemd expects configs in `/etc/openvpn/client/`:

```bash
sudo cp /home/willow/nl-free-125.protonvpn.udp.ovpn /etc/openvpn/client/protonvpn.conf
```

> 📝 Systemd will look for `*.conf` files in that directory.

---

### ✅ 2. Enable the Service

```bash
sudo systemctl enable openvpn-client@protonvpn.service
```

This will:

* Run `openvpn --config /etc/openvpn/client/protonvpn.conf` on boot
* Auto-reconnect on failure
* Integrate well with systemd targets

---

### ✅ 3. Ensure Routing Rule Runs Before VPN

Now we **add a dependency** so that routing gets applied *before* VPN connects.

Edit the OpenVPN client unit override:

```bash
sudo systemctl edit openvpn-client@protonvpn.service
```

Add this:

```ini
[Unit]
After=setup-ssh-route.service
Requires=setup-ssh-route.service
```

This ensures your routing fix is always applied before the VPN tunnel goes up.

---

### ✅ 4. Test Everything

1. Reboot:

   ```bash
   sudo reboot
   ```

2. SSH back in

3. Verify:

   * VPN is connected:

     ```bash
     curl ifconfig.io
     ```

     → should show Netherlands IP

   * Routing rule is present:

     ```bash
     ip rule
     ```

   * Your SSH session is still alive

---

## 🔁 Done!

From now on:

* SSH survives VPN reconnection
* VPN and routing rules apply automatically on boot

Let me know if you also want **reconnect-on-failure** or **kill-switch** behavior.

---

The error message tells us exactly what’s wrong:

> ❌ `--auth-user-pass /home/willow/auth.txt`: **No such file or directory**

OpenVPN is expecting your ProtonVPN **username/password file** at `/home/willow/auth.txt`, but it doesn’t exist (or isn’t readable at boot).

---

## ✅ Fix: Create and Secure the Auth File

### 1. Create the file

```bash
sudo nano /etc/openvpn/client/auth.txt
```

Add your ProtonVPN credentials (not your email, the actual OpenVPN login from the ProtonVPN dashboard):

```
your_protonvpn_username
your_protonvpn_password
```

Save and exit.

---

### 2. Secure the file

```bash
sudo chmod 600 /etc/openvpn/client/auth.txt
sudo chown root:root /etc/openvpn/client/auth.txt
```

---

### 3. Update the Config Path

Edit the OpenVPN config you copied:

```bash
sudo nano /etc/openvpn/client/protonvpn.conf
```

Find this line:

```
auth-user-pass
```

Change it to:

```
auth-user-pass /etc/openvpn/client/auth.txt
```

---

### 4. Restart the Service

```bash
sudo systemctl restart openvpn-client@protonvpn.service
```

Then check status:

```bash
sudo systemctl status openvpn-client@protonvpn.service
```

---

### 🧪 Final Test

After the above:

* SSH should stay connected ✅
* `curl ifconfig.io` should show VPN IP ✅
* `ip rule` should include your SSH rule ✅
* `systemctl status openvpn-client@protonvpn` should show `active (running)` ✅

Let me know if you want to auto-rotate credentials or block traffic if VPN fails (kill switch).
