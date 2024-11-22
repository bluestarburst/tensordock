turnserver \
        -n \
        -a \
        --log-file=stdout \
        --lt-cred-mech \
        --fingerprint \
        --no-stun \
        --no-multicast-peers \
        --no-cli \
        --no-tlsv1 \
        --no-tlsv1_1 \
        --realm="example.org" \
        --user="${TURN_USERNAME:-user}:${TURN_PASSWORD:-${OPEN_BUTTON_TOKEN:-password}}" \
        -p "${VAST_UDP_PORT_70000}" \
        -X "${PUBLIC_IPADDR}" 2>&1 | tee /var/log/coturn.log &

nohup python3 -u server.py > server.log 2>&1 &