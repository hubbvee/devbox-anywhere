#!/bin/bash
# DevboxDrop — ship anything dragged into ~/DevboxDrop to devbox:~/project/_inbox/.
# Runs from launchd (see com.devbox.drop.plist): triggered on folder change + 30s sweep.
# Shipped originals move to ~/DevboxDrop/.sent/ ; remote path -> clipboard + notification.
# Pin ~/DevboxDrop to your Dock and drag files onto it.
#
# Install (macOS):
#   mkdir -p ~/bin ~/DevboxDrop && cp devbox-drop.sh ~/bin/ && chmod +x ~/bin/devbox-drop.sh
#   cp com.devbox.drop.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.devbox.drop.plist

# launchd agents don't inherit SSH_AUTH_SOCK — without this line, passphrase-protected
# keys fail SILENTLY (the #1 "it doesn't work" cause).
export SSH_AUTH_SOCK=${SSH_AUTH_SOCK:-$(ls -t /private/tmp/com.apple.launchd.*/Listeners 2>/dev/null | head -1)}

DROP="$HOME/DevboxDrop"; SENT="$DROP/.sent"; mkdir -p "$SENT"
shopt -s nullglob
for f in "$DROP"/*; do
  base=$(basename "$f")
  [ "$base" = ".DS_Store" ] && continue
  if [ -f "$f" ]; then      # size-settle check: skip files still being copied
    s1=$(stat -f%z "$f"); sleep 1; s2=$(stat -f%z "$f")
    [ "$s1" = "$s2" ] || continue
  fi
  if scp -qr "$f" devbox:project/_inbox/; then
    rm -rf "$SENT/$base"; mv "$f" "$SENT/$base"
    printf '~/project/_inbox/%s' "${base// /\\ }" | pbcopy
    osascript -e "display notification \"~/project/_inbox/$base — path in clipboard\" with title \"DevboxDrop ✓\"" 2>/dev/null
  else
    osascript -e "display notification \"transfer FAILED: $base\" with title \"DevboxDrop ✗\"" 2>/dev/null
  fi
done
