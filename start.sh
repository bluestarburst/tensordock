# Create logs directory in tensordock folder
mkdir -p logs

# Create timestamped log files with absolute paths
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
JUPYTER_LOG="$(pwd)/logs/jupyter_${TIMESTAMP}.log"
SERVER_LOG="$(pwd)/logs/server_${TIMESTAMP}.log"

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
        --user="${TURN_USERNAME:-user}:${TURN_PASSWORD:-password}" \
        -p "${VAST_UDP_PORT_70001:-6000}" \
        -X "${PUBLIC_IPADDR:-localhost}" 2>&1 | tee /var/log/coturn.log &


# Start Jupyter Server in the background at port 8888 with logging
jupyter server --port=8888 --IdentityProvider.token=test > "$JUPYTER_LOG" 2>&1 &

# Start the main server with logging
python -u run_modular.py > "$SERVER_LOG" 2>&1