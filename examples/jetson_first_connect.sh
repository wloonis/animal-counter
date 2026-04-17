#!/bin/bash

JETSON_USER="nano-counter"
JETSON_PASSWORD="&Enniroc1"
WIFI_NETWORK="192.168.0.0/24"

echo "🔍 Scan des machines avec port 22 ouvert..."

# Récupère les IP avec port 22 ouvert
IPS=$(nmap -p 22 --open -oG - $WIFI_NETWORK | awk '/22\/open/{print $2}')

echo "Machines trouvées :"
echo "$IPS"

echo ""
echo "🔐 Tentative de connexion SSH..."

for ip in $IPS; do
    echo "➡️ Test sur $ip"

    sshpass -p "$JETSON_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 $JETSON_USER@$ip "echo '✅ CONNECTÉ à $ip'" 2>/dev/null

    if [ $? -eq 0 ]; then
        echo "🎯 Jetson trouvé : $ip"
        exit 0
    else
        echo "❌ Échec sur $ip"
    fi
done

echo "❗ Aucun Jetson trouvé avec ces identifiants"