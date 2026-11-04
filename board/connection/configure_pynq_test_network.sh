set -eu
# Keep the vendor DHCP/default 192.168.2.99 setup; add the direct-PC test subnet.
target=/etc/network/interfaces.d/zynq_bjt
if [ -e "$target" ]; then
    echo "Existing $target: inspect before replacing" >&2
    exit 1
fi
cat > "$target" <<'EOF'
auto eth0:2
iface eth0:2 inet static
    address 192.168.0.4
    netmask 255.255.255.0
EOF
cat "$target"
