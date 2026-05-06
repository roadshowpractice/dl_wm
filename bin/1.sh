URL='https://www.instagram.com/p/DXYIovWDrRQ/?img_index=2'
IDX=2

IMG_URL=$(
  yt-dlp -J --cookies conf/instagram.cookies.txt "$URL" \
  | python -c '
import json,sys
d=json.load(sys.stdin)
e=(d.get("entries") or [])[int("'"$IDX"'")-1]
print(e.get("display_url") or e.get("url") or e.get("thumbnail") or (e.get("thumbnails") or [{}])[-1].get("url"))
'
)

echo "$IMG_URL"

curl -L "$IMG_URL" \
  -o "outputs/2026-05-02/instagram__DXYIovWDrRQ/instagram__DXYIovWDrRQ__img$(printf '%03d' "$IDX").jpg"
