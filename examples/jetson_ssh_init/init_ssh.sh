#!/bin/bash

# ==============================
# CONFIGURATION
# ==============================

JETSON_HOTSPOT_NAME="" # Dans le .env
JETSON_HOTSPOT_SSID="" # Dans le .env
JETSON_HOTSPOT_PASSWORD="" # Dans le .env
JETSON_HOTSPOT_INTERFACE="" # Dans le .env

BOX_CONNECTION="" # Dans le .env

JETSON_ETH_INTERFACE="" # Dans le .env
JETSON_ETH_IP="" # Dans le .env
JETSON_ETH_GATEWAY="" # Dans le .env

# ==============================
# Activer Wi-Fi et Ethernet
# ==============================

nmcli radio wifi on
sudo nmcli device set $JETSON_ETH_INTERFACE managed yes

# ==============================
# Désactiver la box si elle est active
# ==============================

if nmcli con show --active | grep -q "$BOX_CONNECTION"; then
    echo "Déconnexion de la box $BOX_CONNECTION pour libérer le Wi-Fi..."
    sudo nmcli con down "$BOX_CONNECTION"
fi

# ==============================
# Création du hotspot (si non existant)
# ==============================

if ! nmcli con show "$JETSON_HOTSPOT_NAME" >/dev/null 2>&1; then
    echo "Création du hotspot $JETSON_HOTSPOT_NAME..."
    sudo nmcli con add type wifi ifname "$JETSON_HOTSPOT_INTERFACE" con-name "$JETSON_HOTSPOT_NAME" ssid "$JETSON_HOTSPOT_SSID"
    sudo nmcli con modify "$JETSON_HOTSPOT_NAME" 802-11-wireless.mode ap
    sudo nmcli con modify "$JETSON_HOTSPOT_NAME" 802-11-wireless.band bg
    sudo nmcli con modify "$JETSON_HOTSPOT_NAME" ipv4.method shared    # DHCP automatique pour les clients
    sudo nmcli con modify "$JETSON_HOTSPOT_NAME" wifi-sec.key-mgmt wpa-psk
    sudo nmcli con modify "$JETSON_HOTSPOT_NAME" wifi-sec.psk "$JETSON_HOTSPOT_PASSWORD"
fi

# ==============================
# Priorité hotspot et box
# ==============================

sudo nmcli con modify "$JETSON_HOTSPOT_NAME" connection.autoconnect yes
sudo nmcli con modify "$JETSON_HOTSPOT_NAME" connection.autoconnect-priority 100
sudo nmcli con modify "$BOX_CONNECTION" connection.autoconnect no
sudo nmcli con modify "$BOX_CONNECTION" connection.autoconnect-priority 0

# ==============================
# Création du profil Ethernet si inexistant
# ==============================

if ! nmcli con show "$JETSON_ETH_INTERFACE" >/dev/null 2>&1; then
    sudo nmcli con add type ethernet ifname "$JETSON_ETH_INTERFACE" con-name "$JETSON_ETH_INTERFACE"
fi

# ==============================
# Configuration Ethernet avec IP statique
# ==============================

sudo nmcli con modify "$JETSON_ETH_INTERFACE" ipv4.addresses $JETSON_ETH_IP
sudo nmcli con modify "$JETSON_ETH_INTERFACE" ipv4.gateway $JETSON_ETH_GATEWAY
sudo nmcli con modify "$JETSON_ETH_INTERFACE" ipv4.method manual
sudo nmcli con up "$JETSON_ETH_INTERFACE"

# ==============================
# Activer SSH
# ==============================

sudo systemctl enable ssh
sudo systemctl start ssh

# ==============================
# Autoriser ping + SSH sur hotspot
# ==============================

sudo sysctl -w net.ipv4.icmp_echo_ignore_all=0
sudo iptables -I INPUT -i "$JETSON_HOTSPOT_INTERFACE" -p icmp --icmp-type echo-request -j ACCEPT
sudo iptables -I OUTPUT -o "$JETSON_HOTSPOT_INTERFACE" -p icmp --icmp-type echo-reply -j ACCEPT
sudo iptables -I INPUT -i "$JETSON_HOTSPOT_INTERFACE" -p tcp --dport 22 -j ACCEPT
sudo iptables -I OUTPUT -o "$JETSON_HOTSPOT_INTERFACE" -p tcp --sport 22 -j ACCEPT
