# Running the bot on Oracle Cloud Always Free

The bot runs 24/7 on a free Oracle VM. The Streamlit dashboard is the host
process (same as local): you open it from any device, paste the daily Kite
token, and click **Start live trading**. systemd keeps it alive and restarts
it on crash or reboot.

## 1. Create the free account + VM (one time, ~20 min)

1. Sign up at https://signup.oraclecloud.com (credit card required for
   identity check — Always Free resources are never charged). Pick home
   region **India South (Hyderabad)** or **India West (Mumbai)**.
2. Console → **Compute → Instances → Create instance**:
   - Image: **Ubuntu 24.04**
   - Shape: **Ampere A1.Flex** (Always Free): 2 OCPU / 8 GB is plenty.
     If A1 capacity is unavailable, retry later or use VM.Standard.E2.1.Micro.
   - Add your SSH public key (or download the generated one).
3. Create. Note the instance's **public IP**.

## 2. Install the bot

```bash
ssh ubuntu@<public-ip>
git clone https://github.com/mohanmac/proactive_agentic_dt.git
bash proactive_agentic_dt/deploy/oracle/setup_vm.sh   # stops to let you edit .env
nano proactive_agentic_dt/.env                        # KITE keys, ENABLE_LIVE_TRADING=true
bash proactive_agentic_dt/deploy/oracle/setup_vm.sh   # finishes: installs the service
```

## 3. Private access from your devices (recommended: Tailscale)

Do NOT open port 8501 to the internet (the dashboard has a KILL ALL button
and your live Kite session). Instead join the VM to your tailnet:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # prints a login URL — open it, approve the device
tailscale ip -4            # note the 100.x.x.x address
```

Bookmark `http://<vm-tailscale-ip>:8501` on your phone and laptop. Works on
home Wi-Fi, office 5G, anywhere — visible only to your own devices.

## 4. Daily routine (trading days)

1. Morning (before 10:15 IST): open the dashboard, click **Open Kite login**,
   paste the request_token, **Connect** (Kite tokens expire daily — mandatory).
2. Tick the risk acknowledgement, **Start live trading**.
3. The bot trades 10:15–14:45, force-squares-off at 15:15; guardrails:
   ₹2,000/day capital, ₹200 max daily loss, 5 trades/day max.

## Service management

```bash
sudo systemctl status agentic-dashboard    # health
sudo journalctl -u agentic-dashboard -f    # live logs
sudo systemctl restart agentic-dashboard   # restart
cd ~/proactive_agentic_dt && git pull && sudo systemctl restart agentic-dashboard  # update
```
