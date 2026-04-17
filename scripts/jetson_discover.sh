#!/bin/bash

# Jetson Discovery Script
# Scans network for Jetson devices on SSH port (22)

set -e

# Load environment variables
if [ -f ".env.local" ]; then
    source .env.local
fi

# Check if JETSON_USER is set
if [ -z "${JETSON_USER}" ]; then
    JETSON_USER="nano-counter"
fi

# Check if JETSON_PASSWORD is set
if [ -z "${JETSON_PASSWORD}" ]; then
    echo "Error: JETSON_PASSWORD is not set"
    echo "Please set JETSON_PASSWORD in .env.local"
    exit 1
fi

# Check if sshpass is available
if ! command -v sshpass &> /dev/null; then
    echo "Error: sshpass is not installed. Please install sshpass first."
    exit 1
fi

echo "🔍 Scan des machines avec port 22 ouvert..."

# Récupère les IP avec port 22 ouvert (plusieurs tentatives)
ATTEMPTS=3
for ((i=1; i<=$ATTEMPTS; i++)); do
    echo "Tentative $i/$ATTEMPTS de scan du réseau..."
    IPS=$(nmap -p 22 --open -oG - "$WIFI_NETWORK" | awk '/22\/open/{print $2}')
    
    if [ -n "$IPS" ]; then
        break
    fi
    
    if [ $i -lt $ATTEMPTS ]; then
        sleep 10
    fi
done

echo "Machines trouvées :"
echo "$IPS"

if [ -z "$IPS" ]; then
    echo "❗ Aucun device trouvé avec le port 22 ouvert"
    exit 1
fi

echo ""
echo "🔐 Tentative de connexion SSH..."

for ip in $IPS; do
    echo "➡️ Test sur $ip"
    
    # Supprimer l'entrée connue pour cette IP pour éviter les conflits
    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$ip" 2>/dev/null

    # Augmenter le timeout et ajouter des tentatives
    for ((try=1; try<=3; try++)); do
        echo "  Tentative $try/3..."
        if sshpass -p "$JETSON_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $JETSON_USER@$ip "echo '✅ CONNECTÉ à $ip'" 2>/dev/null; then
            echo "🎯 Jetson trouvé : $ip"
            export JETSON_IP="$ip"
            echo "JETSON_IP=$JETSON_IP" > /tmp/jetson_env.sh
            exit 0
        else
            echo "❌ Échec sur $ip (tentative $try/3)"
            if [ $try -lt 3 ]; then
                sleep 5
            fi
        fi
    done
=======

    if [ $? -eq 0 ]; then
        echo "🎯 Jetson trouvé : $ip"
        export JETSON_IP="$ip"
        echo "JETSON_IP=$JETSON_IP" > /tmp/jetson_env.sh
        exit 0
    else
        echo "❌ Échec sur $ip"
    fi
done

echo "❗ Aucun Jetson trouvé avec ces identifiants"
exit 1
