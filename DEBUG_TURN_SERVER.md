# Debugging TURN Server on DigitalOcean

## Quick Debugging Commands

### 1. Check if TURN Server Process is Running

```bash
# Check if turnserver process is running
ps aux | grep turnserver

# Check supervisor status
supervisorctl status

# Check if turn_server is running via supervisor
supervisorctl status turn_server
```

### 2. Check if Port is Listening

```bash
# Check what port TURN is configured to use
grep VAST_UDP_PORT_70001 /opt/tensordock/runtime.env
# Or check the actual port number
cat /opt/tensordock/runtime.env | grep VAST_UDP_PORT_70001

# Check if the port is listening (replace 50000 with your actual port)
netstat -ulnp | grep 50000
# Or using ss (more modern)
ss -ulnp | grep 50000

# Check all UDP ports in use
ss -ulnp

# Check if turnserver is listening on any port
ss -ulnp | grep turnserver
```

### 3. Check Firewall Rules (UFW)

```bash
# Check UFW status
sudo ufw status verbose

# Check if your TURN port is allowed
sudo ufw status | grep 50000

# Check numbered rules
sudo ufw status numbered

# Check UFW logs for blocked connections
sudo tail -f /var/log/ufw.log
```

### 4. View TURN Server Logs

```bash
# View supervisor TURN server log
tail -f /var/log/supervisor/turn_server.log

# View last 100 lines
tail -n 100 /var/log/supervisor/turn_server.log

# View coturn log (if it exists)
tail -f /var/log/coturn.log

# View supervisor main log
tail -f /var/log/supervisor/supervisord.log

# Check systemd journal for supervisor service
journalctl -u tensordock-supervisor.service -f
```

### 5. Check Environment Variables

```bash
# Check runtime environment variables
cat /opt/tensordock/runtime.env

# Check if VAST_UDP_PORT_70001 is set correctly
grep VAST_UDP_PORT_70001 /opt/tensordock/runtime.env

# Check what port supervisor thinks TURN should use
supervisorctl status turn_server
# Then check the actual command being run
cat /etc/supervisor/conf.d/supervisord.conf | grep -A 5 "program:turn_server"
```

### 6. Test Port Connectivity

```bash
# From the DigitalOcean droplet itself, test UDP port
# Install netcat if needed: apt-get install netcat
nc -u -v localhost 50000

# Test from external machine (replace with your droplet IP and port)
# On your local machine:
nc -u -v YOUR_DROPLET_IP 50000

# Check if port is reachable from outside
# Use an online tool like https://www.yougetsignal.com/tools/open-ports/
# Or use telnet for TCP (won't work for UDP, but shows if port is open)
telnet YOUR_DROPLET_IP 50000
```

### 7. Check Network Interfaces and IPs

```bash
# Check all network interfaces
ip addr show
# Or
ifconfig

# Check public IP
curl -s https://ifconfig.co
# Or DigitalOcean metadata
curl -s http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address

# Check what IP turnserver is binding to
ss -ulnp | grep turnserver
```

### 8. Verify TURN Server Configuration

```bash
# Check the actual turnserver command being run
# Look at supervisor config
cat /etc/supervisor/conf.d/supervisord.conf | grep -A 10 "program:turn_server"

# Check if START_TURN is set to true
grep START_TURN /opt/tensordock/runtime.env

# Manually test turnserver command (as appuser)
sudo -u appuser /usr/bin/turnserver --help
```

### 9. Check for Port Conflicts

```bash
# Check if anything else is using port 50000
sudo lsof -i :50000
# Or
sudo fuser 50000/udp

# Check all processes using UDP ports
sudo netstat -ulnp
```

### 10. Test TURN Server Functionality

```bash
# Install turnutils (coturn utilities) if available
apt-get install coturn-utils

# Test TURN server with turnutils_stunclient
turnutils_stunclient YOUR_DROPLET_IP -p 50000

# Test with turnutils_peer
turnutils_peer -p 50000 YOUR_DROPLET_IP
```

## Common Issues and Solutions

### Issue: TURN server not starting
- Check supervisor logs: `tail -f /var/log/supervisor/turn_server.log`
- Check if START_TURN=true: `grep START_TURN /opt/tensordock/runtime.env`
- Check if port is already in use: `sudo lsof -i :50000`

### Issue: Port not accessible from outside
- Check UFW rules: `sudo ufw status`
- Verify port is allowed: `sudo ufw allow 50000/udp`
- Check DigitalOcean Cloud Firewall (via web console)
- Verify turnserver is binding to 0.0.0.0, not 127.0.0.1

### Issue: TURN server crashes repeatedly
- Check logs for errors: `tail -100 /var/log/supervisor/turn_server.log`
- Check if SQLite DB directory exists and is writable
- Check if certificate files are needed (we disabled TLS, so shouldn't be needed)

### Issue: Port mismatch
- Verify VAST_UDP_PORT_70001 matches actual listening port
- Check runtime.env: `grep VAST_UDP_PORT_70001 /opt/tensordock/runtime.env`
- Check what port turnserver is actually using: `ss -ulnp | grep turnserver`

## Debugging Checklist

- [ ] TURN server process is running (`ps aux | grep turnserver`)
- [ ] Supervisor shows turn_server as RUNNING (`supervisorctl status`)
- [ ] Port is listening (`ss -ulnp | grep 50000`)
- [ ] UFW allows the port (`sudo ufw status | grep 50000`)
- [ ] Port is accessible from outside (test with nc or online tool)
- [ ] VAST_UDP_PORT_70001 is set correctly in runtime.env
- [ ] START_TURN is set to true
- [ ] No port conflicts (`sudo lsof -i :50000`)
- [ ] TURN server logs show successful startup
- [ ] Public IP is correctly detected and used

## Quick One-Liner to Check Everything

```bash
echo "=== TURN Server Debug Info ===" && \
echo "Process:" && ps aux | grep turnserver | grep -v grep && \
echo -e "\nSupervisor Status:" && supervisorctl status turn_server && \
echo -e "\nPort Listening:" && ss -ulnp | grep -E "(turnserver|50000)" && \
echo -e "\nUFW Status:" && sudo ufw status | grep 50000 && \
echo -e "\nEnvironment:" && grep -E "(VAST_UDP_PORT_70001|START_TURN)" /opt/tensordock/runtime.env && \
echo -e "\nRecent Logs:" && tail -20 /var/log/supervisor/turn_server.log
```

