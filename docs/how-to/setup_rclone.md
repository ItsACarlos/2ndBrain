# Rclone Setup: Encrypted & Restricted

```{note}
Most of this guide is automated by running `./scripts/setup-gpg-pass.sh` followed by
`./scripts/install.sh`. The scripts will prompt you to install any missing system
packages (rclone, fuse3, pass). Read on if you need to understand the
individual steps or troubleshoot.
```

This guide provides a secure, portable method for mounting a specific Google Drive folder to a local Linux directory (`~/Documents/2ndBrain`).

## 1. Prerequisites

**Minimum rclone version: 1.58.0** (required for `bisync` command)

### Ubuntu/Debian/Mint

```bash
sudo apt install rclone fuse3 pass

# Verify rclone version (must be ≥ 1.58.0)
rclone version
```

### RHEL/CentOS 8: Upgrade rclone

The RHEL8 repository includes rclone 1.57.0, which predates the `bisync`
command. Install the latest version directly from rclone.org:

```bash
# Install dependencies
sudo yum install fuse3 pass

# Download and install latest rclone
curl https://rclone.org/install.sh | sudo bash

# Verify version (should be ≥ 1.58.0)
rclone version
```

### Fedora/CentOS Stream

Newer Fedora releases have rclone ≥ 1.58.0:

```bash
sudo dnf install rclone fuse3 pass

# Verify version
rclone version
```

(rhel-centos-8-upgrade-rclone)=
### RHEL/CentOS 8: Upgrade rclone

## 2. Configuration Strategy

To ensure the mount is both secure and portable, we use three key principles:

1. **Config Encryption:** The `rclone.conf` is password-protected.
2. **Root Isolation:** Use the `root_folder_id` in the config to lock access to a single folder.
3. **GPG Encryption:** Store the password encrypted with GPG using `pass` and `gpg-agent`.

---

## 3. Security: GPG-Encrypted Password Storage

We'll use `pass` (the standard Unix password manager) with GPG encryption, configured with `gpg-agent` to cache the passphrase for automated access.

### Step 1: Create or Use Existing GPG Key

```bash
# Check if you already have a GPG key
gpg --list-keys

# If you don't have one, create it (follow prompts, set a strong passphrase)
gpg --full-generate-key
```

### Step 2: Configure gpg-agent for Long Caching

```bash
# Configure gpg-agent to cache passphrases indefinitely
mkdir -p ~/.gnupg
cat >> ~/.gnupg/gpg-agent.conf << 'EOF'
default-cache-ttl 34560000
max-cache-ttl 34560000
allow-preset-passphrase
EOF

# Restart gpg-agent to apply settings
gpgconf --kill gpg-agent
gpg-agent --daemon
```

### Step 3: Initialize pass and Store Password

```bash
# Initialize pass with your GPG key (use the email from gpg --list-keys)
pass init "your-email@example.com"

# Store the rclone config password
pass insert rclone/gdrive-vault
```

### Step 4: Setup Automatic Passphrase Preset at Login

Get your GPG key's keygrip and create a preset script:

```bash
# Get the keygrip (avoid storing in history by using redirection)
gpg --with-keygrip -K | grep -A1 "ssb" | tail -1 | awk '{print $3}' > /tmp/keygrip.txt

# View it to verify
cat /tmp/keygrip.txt

# Create a preset script (will prompt for your GPG passphrase)
mkdir -p ~/.local/bin
cat > ~/.local/bin/preset-gpg-passphrase.sh << 'EOF'
#!/bin/bash
# Read keygrip from file
KEYGRIP=$(cat ~/.gnupg/keygrip.txt)

# Prompt for passphrase securely (won't echo to screen)
read -sp "Enter GPG passphrase: " GPG_PASS
echo

# Preset the passphrase
echo "$GPG_PASS" | /usr/lib/gnupg/gpg-preset-passphrase --preset "$KEYGRIP"
EOF

chmod +x ~/.local/bin/preset-gpg-passphrase.sh

# Move keygrip to permanent location
mv /tmp/keygrip.txt ~/.gnupg/keygrip.txt
chmod 600 ~/.gnupg/keygrip.txt
```

### Step 5: Add to Login Script

Add this to your `~/.bashrc` or `~/.profile`:

```bash
# Auto-preset GPG passphrase on login (run once per session)
if [ -z "$GPG_PRESET_DONE" ]; then
    if [ -f ~/.local/bin/preset-gpg-passphrase.sh ]; then
        ~/.local/bin/preset-gpg-passphrase.sh
        export GPG_PRESET_DONE=1
    fi
fi
```

Now when you login via SSH, you'll be prompted once for your GPG passphrase, and it will be cached for the systemd service to use.

---

## 4. Systemd Service

Create the systemd service file at `~/.config/systemd/user/rclone-2ndbrain.service`. It uses specifiers (`%U`, `%h`) to work on any machine regardless of username or UID.

```bash
# Create the systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Create the service file
cat > ~/.config/systemd/user/rclone-2ndbrain.service << 'EOF'
[Unit]
Description=RClone Mount for 2ndBrain
After=network-online.target

[Service]
Type=simple
# Note: 'gdrive-vault:' points to the root_folder_id set in config
ExecStart=/usr/bin/rclone mount gdrive-vault: %h/Documents/2ndBrain \
  --password-command "pass rclone/gdrive-vault" \
  --vfs-cache-mode full \
  --vfs-cache-max-age 24h \
  --vfs-cache-max-size 10G
ExecStop=/usr/bin/fusermount -u %h/Documents/2ndBrain
Restart=on-failure

[Install]
WantedBy=default.target
EOF
```

---

## 5. Deployment & Maintenance

### Launching the System

```bash
# Create the mount point directory
mkdir -p ~/Documents/2ndBrain

# Enable lingering to allow service to run on boot without login
sudo loginctl enable-linger $USER

# Reload systemd and start the service
systemctl --user daemon-reload
systemctl --user enable --now rclone-2ndbrain.service

# Check the status
systemctl --user status rclone-2ndbrain.service
```

### The "Nuclear" Reset (For 'Directory Busy' errors)

If the mount hangs or shows as "already mounted," run this clean-up:

```bash
# 1. Stop the process
systemctl --user stop rclone-2ndbrain.service

# 2. Force Lazy Unmount
sudo umount -l ~/Documents/2ndBrain

# 3. Clear VFS Cache
rm -rf ~/.cache/rclone/vfs/gdrive-vault/

# 4. Restart
systemctl --user start rclone-2ndbrain.service
```

---

## 6. Portability (Moving to Machine 2)

To replicate this setup on a new machine:

```bash
old_machine="user@old_machine_ip"  # Replace with actual username and IP

# Install dependencies
sudo apt install rclone fuse3 pass

# Create necessary directories
mkdir -p ~/.config/rclone
mkdir -p ~/.config/systemd/user
mkdir -p ~/.local/bin
mkdir -p ~/Documents/2ndBrain

# Copy rclone config and systemd service
scp $old_machine:~/.config/rclone/rclone.conf ~/.config/rclone/
scp $old_machine:~/.config/systemd/user/rclone-2ndbrain.service ~/.config/systemd/user/

# Copy GPG keys and password store
scp -r $old_machine:~/.gnupg ~/
scp -r $old_machine:~/.password-store ~/

# Copy the preset passphrase script
scp $old_machine:~/.local/bin/preset-gpg-passphrase.sh ~/.local/bin/
chmod +x ~/.local/bin/preset-gpg-passphrase.sh

# Fix permissions
chmod 700 ~/.gnupg
chmod 700 ~/.password-store

# Add the auto-preset to ~/.bashrc (if not already there)
cat >> ~/.bashrc << 'EOF'

# Auto-preset GPG passphrase on login (run once per session)
if [ -z "$GPG_PRESET_DONE" ]; then
    if [ -f ~/.local/bin/preset-gpg-passphrase.sh ]; then
        ~/.local/bin/preset-gpg-passphrase.sh
        export GPG_PRESET_DONE=1
    fi
fi
EOF
```

**Test the setup:**

```bash
# Logout and login again (to trigger the bashrc preset)
# Or manually run the preset script once
~/.local/bin/preset-gpg-passphrase.sh

# Verify you can access the password without prompts
pass rclone/gdrive-vault

# Start the service
systemctl --user daemon-reload
systemctl --user enable --now rclone-2ndbrain.service

# Check status
systemctl --user status rclone-2ndbrain.service
```
