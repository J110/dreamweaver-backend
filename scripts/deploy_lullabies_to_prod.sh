#!/bin/bash
# Deploy test lullabies to GCP production
# Run from local machine after lullabies are generated
set -e

REMOTE="dreamvalley-prod"
SSH="gcloud compute ssh $REMOTE --project=strong-harbor-472607-n4 --zone=asia-south1-a --command"
SCP="gcloud compute scp --project=strong-harbor-472607-n4 --zone=asia-south1-a"

BACKEND_DIR="/Users/anmolmohan/Music/Bed Time Story App/dreamweaver-backend"
FRONTEND_DIR="/Users/anmolmohan/Music/Bed Time Story App/dreamweaver-web"
LULLABY_DIR="$BACKEND_DIR/seed_output/lullabies"

echo "=== Deploying test lullabies to production ==="

# 1. Check lullabies exist locally
echo "1. Checking local files..."
ls -la "$LULLABY_DIR"/*.mp3 || { echo "ERROR: No MP3 files found!"; exit 1; }
ls -la "$LULLABY_DIR"/lullabies.json || { echo "ERROR: No lullabies.json found!"; exit 1; }

# 2. Create remote directories
echo "2. Creating remote directories..."
$SSH "sudo mkdir -p /opt/dreamweaver-web/public/audio/lullabies && sudo mkdir -p /opt/dreamweaver-web/public/covers/lullabies && sudo chown -R anmolmohan:anmolmohan /opt/dreamweaver-web/public/audio/lullabies /opt/dreamweaver-web/public/covers/lullabies"

# 3. Copy audio files
echo "3. Uploading audio files..."
$SCP "$LULLABY_DIR"/*.mp3 $REMOTE:/opt/dreamweaver-web/public/audio/lullabies/

# 4. Copy cover files
echo "4. Uploading cover files..."
$SCP "$LULLABY_DIR"/*_cover.svg $REMOTE:/opt/dreamweaver-web/public/covers/lullabies/

# 5. Copy lullabies.json to backend
echo "5. Uploading lullabies.json..."
$SSH "mkdir -p /opt/dreamweaver-backend/seed_output/lullabies"
$SCP "$LULLABY_DIR"/lullabies.json $REMOTE:/opt/dreamweaver-backend/seed_output/lullabies/

# 6. Add nginx rules for lullaby audio/covers (if not already added)
echo "6. Checking nginx config..."
$SSH "sudo grep -q 'audio/lullabies' /etc/nginx/sites-available/dreamvalley.app || echo 'NOTE: Add nginx aliases for /audio/lullabies/ and /covers/lullabies/ manually'"

echo ""
echo "=== Done! ==="
echo "Audio at: https://dreamvalley.app/audio/lullabies/"
echo "Covers at: https://dreamvalley.app/covers/lullabies/"
echo "API at: https://api.dreamvalley.app/api/v1/lullabies"
echo "Page at: https://dreamvalley.app/lullabies"
echo ""
echo "Next steps:"
echo "  1. Rebuild backend Docker: cd /opt/dreamweaver-backend && sudo docker-compose down && sudo docker-compose up -d --build"
echo "  2. Rebuild frontend: cd /opt/dreamweaver-web && git pull && sudo npm run build && sudo cp -r public .next/standalone/public && sudo cp -r .next/static .next/standalone/.next/static && sudo pm2 restart dreamweaver-web"
echo "  3. Add nginx aliases if not present"
