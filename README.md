# BoxTrack

A mobile-friendly home inventory app. Define items with photos, assign them to boxes or locations, print QR labels, and scan them to instantly pull up a box's contents. Includes visual search — take a photo of an object and find matching items in your inventory.

## Features

- **Items** — name, description, photo
- **Boxes / Locations** — unique code, description, QR label
- **QR codes** — print labels, scan with any phone camera to open a box
- **Visual search** — take a photo, find matching items using CLIP embeddings
- **Mobile-first UI** — works well on phone while sorting boxes

## Requirements

- Python 3.10+
- `openssl` (for HTTPS / camera access)
- `mkcert` (recommended — makes the cert trusted on your devices)

## Install

```bash
git clone https://github.com/YOUR_USERNAME/boxtrack.git
cd boxtrack

python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### HTTPS setup (required for camera / QR scanning)

Generate a trusted local certificate with [mkcert](https://github.com/FiloSottile/mkcert):

```bash
sudo apt install mkcert libnss3-tools   # Ubuntu/Debian
mkcert -install
mkcert YOUR_LOCAL_IP YOUR_HOSTNAME localhost
mv YOUR_LOCAL_IP+*.pem cert.pem
mv YOUR_LOCAL_IP+*-key.pem key.pem
```

Replace `YOUR_LOCAL_IP` with your machine's LAN IP (e.g. `192.168.1.100`) and `YOUR_HOSTNAME` with its hostname (e.g. `mypc.local`). Find your IP with `ip route get 1` or `hostname -I`.

Once installed, visit `https://YOUR_LOCAL_IP:5000` from every device and accept the certificate once. After that there are no warnings.

> **Without mkcert:** you can still generate a self-signed cert, but browsers will warn on every visit and the in-app QR scanner won't work (camera API requires HTTPS with a trusted cert). The phone's native camera app can still scan QR codes — it opens the URL directly without needing the in-app scanner.

## Run

```bash
./run.sh
```

Then open `https://YOUR_LOCAL_IP:5000` in a browser. Keep the terminal open — the server stops when you close it.

To run in the background (survives closing the terminal):

```bash
nohup ./run.sh &
# or in a tmux session:
tmux new -s boxtrack
./run.sh
# Ctrl+B then D to detach
```

## Usage

### Adding items
1. **Items → + New** — add a name, optional description, and photo
2. Photos are used for visual search, so add them where you can

### Adding boxes
1. **Boxes → + New** — give the box a name and a short code (auto-generated, or type your own)
2. Open a box → search for items to add, set quantities

### QR labels
1. **Print** — shows a grid of all boxes with QR codes, name, and code
2. Print the page and cut out the labels
3. Scan with your phone's camera app — tapping the link opens that box directly

### Visual search
1. **Items → Find** — takes or uploads a photo
2. Returns your inventory items ranked by visual similarity
3. First use: tap **Index now** to generate embeddings for existing item photos (downloads the CLIP model ~340 MB on first run, cached after that)
4. New items with photos are indexed automatically

## Data

- **Database:** `inventory.db` (SQLite, created automatically)
- **Photos:** `uploads/` directory
- **Neither is committed to git** — back them up separately if needed

## Visual search notes

Uses [CLIP ViT-B/32](https://huggingface.co/openai/clip-vit-base-patch32) from OpenAI via HuggingFace. The model runs locally — no data leaves your machine. CPU inference takes 2–4 seconds per search on a typical desktop. If you have an NVIDIA GPU with working drivers, PyTorch will use it automatically (sub-second).
